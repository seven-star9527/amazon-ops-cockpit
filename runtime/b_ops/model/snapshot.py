"""Normalize live Lingxing rows; missing periods never become invented zeroes."""

from __future__ import annotations

from collections import defaultdict

from .identity import product_key


PERFORMANCE_FIELDS = {
    "volume": "units", "amount": "sales", "avg_custom_price": "avg_price",
    "sessions_total": "sessions_total", "clicks": "ad_clicks",
    "order_items": "orders", "spend": "ad_spend", "ad_sales_amount": "ad_sales",
    "return_goods_count": "return_count", "return_goods_rate": "return_rate",
    "shared_ads_sb_cost": "sb_spend", "ads_sp_cost": "sp_spend",
    "impressions": "impressions", "ad_order_quantity": "ad_orders",
    "nature_order_items": "natural_orders", "acos": "acos", "tacos": "acoas",
    "cpc": "cpc", "ad_cvr": "ad_cvr", "nature_order_rate": "natural_order_share",
}


def number(value):
    if value is None or isinstance(value, bool) or str(value).strip() in {"", "***", "--", "-"}:
        return None
    try:
        return float(str(value).replace(",", ""))
    except ValueError:
        return None


def _sid(row):
    value = row.get("sid") or row.get("s_id") or row.get("store_id") or row.get("storeId")
    return str(value).strip() if value is not None else ""


def normalize_products(raw: dict, weeks: list[dict]) -> tuple[dict[str, dict], dict]:
    shops = {_sid(row): row for row in raw.get("shops", []) if _sid(row)}
    products = {}
    by_sid_asin = {}
    gaps = {"unmapped_listing_rows": 0, "unmapped_fba_rows": 0, "unmapped_performance_rows": 0, "summary_performance_rows": 0,
            "stock_unknown_skus": 0, "performance_missing_weeks": 0}
    for row in raw.get("listings", []):
        sid, asin = _sid(row), str(row.get("asin") or "").strip().upper()
        if not sid or sid not in shops or not asin:
            gaps["unmapped_listing_rows"] += 1
            continue
        shop = shops[sid]
        site = str(shop.get("country_code") or shop.get("site_code") or "").split("-")[-1].upper()
        if not site:
            gaps["unmapped_listing_rows"] += 1
            continue
        key = product_key(sid, site, asin)
        msku = str(row.get("msku") or "").strip()
        parent_asin = str(row.get("parent_asin") or "").strip().upper()
        if key not in products:
            products[key] = {
                "key": key, "sid": sid, "site": site, "asin": asin,
                "parent_asin": parent_asin or None,
                "shop": str(shop.get("name") or shop.get("seller_name") or sid),
                "currency": str(shop.get("currency") or ""),
                "name": str(row.get("local_name") or row.get("item_name") or asin),
                "english_title": str(row.get("item_name") or ""),
                "url": str(row.get("asin_url") or f"https://www.amazon.com/dp/{asin}"),
                "status": str(row.get("status") or ""), "status_text": str(row.get("status_text") or ""),
                "rating": number(row.get("stars")), "reviews": number(row.get("reviews_num")),
                "price": number(row.get("price")),
                "content": {"title": str(row.get("item_name") or "").strip(),
                            "main_image_url": str(row.get("small_image_url") or "").strip() or None,
                            "bullets": None, "gallery_urls": None, "source": "erp_listing"},
                "skus": {}, "stock": {},
                "weeks": [{**week, **{field: None for field in PERFORMANCE_FIELDS.values()},
                           "natural_sessions_est": None, "quality": "missing", "source_ref": None} for week in weeks],
            }
            by_sid_asin[(sid, asin)] = key
        product = products[key]
        if parent_asin:
            if product["parent_asin"] and product["parent_asin"] != parent_asin:
                raise ValueError(f"conflicting parent ASIN for {sid}|{asin}")
            product["parent_asin"] = parent_asin
        if str(row.get("status")) == "1":
            product["status"] = "1"
            if row.get("local_name"):
                product["name"] = str(row["local_name"])
        if msku:
            if msku in product["skus"]:
                raise ValueError(f"duplicate MSKU {sid}|{asin}|{msku}")
            product["skus"][msku] = {
                "msku": msku, "fnsku": row.get("fnsku"),
                "sellable": number(row.get("afn_fulfillable_quantity")),
                "inbound_shipped": number(row.get("afn_inbound_shipped_quantity")),
                "inbound_receiving": number(row.get("afn_inbound_receiving_quantity")),
                "inbound_working": number(row.get("afn_inbound_working_quantity")),
                "reserved": number(row.get("afn_reserved_quantity")),
                "unsellable": number(row.get("afn_unsellable_quantity")),
                "source": "erp_listing",
            }
    for product in products.values():
        skus = list(product["skus"].values())
        for field in ("sellable", "inbound_shipped", "inbound_receiving", "inbound_working", "reserved", "unsellable"):
            values = [sku[field] for sku in skus]
            product["stock"][field] = sum(values) if values and all(value is not None for value in values) else None
            if values and any(value is None for value in values):
                gaps["stock_unknown_skus"] += 1
    fba_fields = {
        "afn_fulfillable_quantity": "sellable", "real_transit_quantity": "transit",
        "estimated_excess_quantity": "excess_estimate",
        "inv_age_181_to_270_days": "age_181_270",
        "inv_age_271_to_365_days": "age_271_365",
        "inv_age_365_plus_days": "age_365_plus",
        "estimated_storage_cost_next_month": "storage_cost_next_month",
    }
    fba_aggregates = defaultdict(lambda: defaultdict(list))
    for row in raw.get("stock", []):
        sid, asin = _sid(row), str(row.get("asin") or "").upper()
        key = by_sid_asin.get((sid, asin))
        if key is None:
            gaps["unmapped_fba_rows"] += 1
            continue
        for source_field, target_field in fba_fields.items():
            fba_aggregates[key][target_field].append(number(row.get(source_field)))
        fba_aggregates[key]["_rows"].append(1)
    for key, fields in fba_aggregates.items():
        stock = products[key]["stock"]
        stock["listing_sellable"] = stock.get("sellable")
        for field in fba_fields.values():
            values = fields.get(field) or []
            stock[field] = sum(values) if values and all(item is not None for item in values) else None
        age = [stock.get(name) for name in ("age_181_270", "age_271_365", "age_365_plus")]
        stock["age_181_plus"] = sum(age) if all(value is not None for value in age) else None
        stock["fba_rows"] = len(fields["_rows"])
        stock["source"] = "get_fba_stock_list"
    for key, product in products.items():
        if key not in fba_aggregates:
            product["stock"]["listing_sellable"] = product["stock"].get("sellable")
            product["stock"]["sellable"] = None
            product["stock"]["source"] = "listing_only_unverified"
    week_map = {week["start"]: week for week in weeks}
    staged = set()
    for row in raw.get("performance", []):
        sid = str(row.get("_requested_sid") or "")
        start = str(row.get("_week_start") or "")
        week = week_map.get(start)
        if week is None or str(row.get("rdate") or "") != f"{week['start']}~{week['end']}":
            raise ValueError("performance week mismatch")
        row_sids = {str(value) for value in row.get("sids") or []}
        if row_sids != {sid}:
            raise ValueError("performance store mismatch")
        asin = str(row.get("asin") or "").strip().upper()
        if not asin or asin == "-":
            gaps["summary_performance_rows"] += 1
            continue
        key = by_sid_asin.get((sid, asin))
        if key is None:
            gaps["unmapped_performance_rows"] += 1
            continue
        if (key, start) in staged:
            raise ValueError("duplicate performance product/week")
        staged.add((key, start))
        target = next(item for item in products[key]["weeks"] if item["start"] == start)
        for source_field, target_field in PERFORMANCE_FIELDS.items():
            target[target_field] = number(row.get(source_field))
        total, ads = target["sessions_total"], target["ad_clicks"]
        if target.get("units") is not None:
            target["daily_units"] = round(target["units"] / 7, 2)
        if total and target.get("orders") is not None:
            target["total_cvr"] = round(target["orders"] / total, 4)
        if target.get("ad_orders") is not None and target.get("orders"):
            target["ad_order_share"] = round(target["ad_orders"] / target["orders"], 4)
        if ads is not None and target.get("impressions"):
            target["ad_click_rate"] = round(ads / target["impressions"], 5)
        if total is not None and ads is not None and 0 <= ads <= total:
            target["natural_sessions_est"] = total - ads
        elif total is not None and ads is not None:
            target["natural_sessions_quality"] = "conflicting"
        target["quality"] = "measured"
        target["source_ref"] = row.get("_source_ref")
    gaps["performance_missing_weeks"] = sum(
        week["quality"] == "missing" for product in products.values() for week in product["weeks"])
    return products, gaps
