"""Four read-only supply datasets. Hosts own authentication and current grants.

Facts have stable line identities; purchase, receipt and FBA quantities are
different stages of the same goods and must never be added to current stock.
"""
from __future__ import annotations

import copy
import datetime as dt
from collections import Counter

from .lingxing_supply import SupplyError, _date, _qty

FBA_PATH = "/erp/sc/data/fba_report/shipmentList"
PRODUCT_PATH = "/erp/sc/routing/data/local_inventory/productInfo"
PURCHASE_PATH = "/erp/sc/routing/data/local_inventory/purchaseOrderList"
RECEIPT_PATH = "/erp/sc/routing/deliveryReceipt/PurchaseReceiptOrder/getOrderList"
READ_PATHS = frozenset({FBA_PATH, PRODUCT_PATH, PURCHASE_PATH, RECEIPT_PATH})
SCHEMA = "lingxing-supply-details.v1"


def _unique(rows, key):
    result = {}
    for row in rows:
        identity = key(row)
        if not identity or any(v in (None, "") for v in identity):
            raise SupplyError("MISSING_LINE_IDENTITY")
        if identity in result and result[identity] != row:
            raise SupplyError("CONFLICTING_DUPLICATE_LINE")
        result[identity] = row
    return list(result.values())


def collect_details(read_api, *, snapshot, allowed_sids, start_date, max_calls=300):
    """Collect an explicit historical window, not an assertion of all-time stock.

    Paginate before publishing a dataset. Incomplete datasets are not used for
    calculations. API credentials may cover more shops: filter lines in memory
    before returning anything to the host/cache/panel. sid=0 is never guessed.
    """
    allowed = {str(s) for s in allowed_sids}
    records = snapshot.get("records", [])
    as_of = snapshot.get("metadata", {}).get("asOf")
    if not records or not allowed or any(str(r.get("storeId")) not in allowed for r in records):
        raise SupplyError("STORE_SCOPE_DENIED")
    if _date(start_date) != start_date or _date(as_of) != as_of or start_date > as_of:
        raise SupplyError("INVALID_DATE_WINDOW")
    if isinstance(max_calls, bool) or not isinstance(max_calls, int) or max_calls < 1:
        raise SupplyError("INVALID_CALL_BUDGET")
    skus = sorted({s for r in records for s in r.get("skus", [r.get("sku")]) if s})
    calls = 0
    audit = []

    def call(path, body):
        nonlocal calls
        if path not in READ_PATHS or calls >= max_calls:
            raise SupplyError("CALL_BUDGET_EXHAUSTED")
        calls += 1
        try:
            response = read_api(path, body)
        except Exception:
            raise SupplyError("API_TRANSPORT_ERROR") from None
        if not isinstance(response, dict) or response.get("code") != 0 or response.get("success") is False:
            raise SupplyError("API_BUSINESS_ERROR")
        audit.append({"path": path, "request_id": response.get("request_id"), "response_time": response.get("response_time")})
        return response

    def pages(path, body):
        offset, expected, rows, seen = 0, None, [], set()
        while True:
            response = call(path, {**body, "offset": offset, "length": 500})
            data = response.get("data")
            page = data if isinstance(data, list) else data.get("list") if isinstance(data, dict) else None
            total = _qty(data.get("total", response.get("total")) if isinstance(data, dict) else response.get("total"))
            if not isinstance(page, list) or any(not isinstance(r, dict) for r in page) or total is None:
                raise SupplyError("API_PAGE_SHAPE_ERROR")
            if expected is not None and total != expected:
                raise SupplyError("API_PAGE_TOTAL_CHANGED")
            expected = total
            for row in page:
                identity = (str(row.get("sid", "")), row.get("shipment_id")) if path == FBA_PATH else row.get("order_sn")
                if not identity or identity in seen:
                    raise SupplyError("API_PAGE_OVERLAP")
                seen.add(identity)
            rows.extend(page)
            offset += len(page)
            if offset == total:
                return rows
            if not page or offset > total:
                raise SupplyError("API_INCOMPLETE_PAGE")

    result = {"schema": SCHEMA, "as_of": as_of, "window_start": start_date,
              "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
              "products": [], "shipments": [], "purchases": [], "receipts": [], "states": {}, "errors": {}}
    # Each dataset is atomic. One failed endpoint does not erase unrelated facts.
    for kind, path, body in [
        ("shipments", FBA_PATH, {"sid": ",".join(sorted(allowed)), "start_date": start_date,
                                 "end_date": (dt.date.fromisoformat(as_of) + dt.timedelta(days=1)).isoformat()}),
        ("purchases", PURCHASE_PATH, {"start_date": start_date, "end_date": as_of, "search_field_time": "create_time"}),
        ("receipts", RECEIPT_PATH, {"start_date": start_date, "end_date": as_of, "date_type": 2, "status": 40, "order_type": 1}),
    ]:
        try:
            raw = pages(path, body)
            normalized = []
            for order in raw:
                items = order.get("item_list")
                if not isinstance(items, list):
                    raise SupplyError("API_ITEMS_SHAPE_ERROR")
                for item in items:
                    sid = str(order.get("sid")) if kind == "shipments" else str(item.get("sid" if kind == "purchases" else "seller_id"))
                    if sid not in allowed:
                        continue
                    row = {"sid": sid, "sku": item.get("sku")}
                    if kind == "shipments":
                        row.update(shipment_id=order.get("shipment_id"), status=order.get("shipment_status"),
                                   asin=item.get("asin"), msku=item.get("msku"), fnsku=item.get("fnsku"),
                                   declared_qty=_qty(item.get("quantity_shipped")), received_qty=_qty(item.get("quantity_received")),
                                   local_shipped_qty=_qty(item.get("quantity_shipped_local")), carton_qty=_qty(item.get("quantity_in_case")))
                    elif kind == "purchases":
                        row.update(order_sn=order.get("order_sn"), item_id=str(item.get("id") or ""),
                                   status=str(order.get("status")), arrival_status=str(order.get("status_shipped")),
                                   deleted=str(item.get("is_delete")), ordered_qty=_qty(item.get("quantity_real")),
                                   pending_qty=_qty(item.get("quantity_receive")), stocked_qty=_qty(item.get("quantity_entry")),
                                   returned_qty=_qty(item.get("quantity_return")), exchanged_qty=_qty(item.get("quantity_exchange")),
                                   expected_date=_date(item.get("expect_arrive_time")), carton_qty=_qty(item.get("quantity_per_case")))
                    else:
                        row.update(order_sn=order.get("order_sn"), item_id=str(item.get("item_id") or ""),
                                   purchase_order=order.get("business_order_sn"), purchase_item_id=str(item.get("order_item_id") or ""),
                                   status=str(order.get("status")), actual_qty=_qty(item.get("product_receive_num")),
                                   actual_time=order.get("receive_time") if _date(order.get("receive_time")) else None,
                                   expected_date=_date(order.get("expect_arrival_time")))
                    normalized.append(row)
            key = (lambda r: (r["sid"], r["shipment_id"], r["msku"], r["fnsku"], r["sku"])) if kind == "shipments" else (lambda r: (r["order_sn"], r["item_id"]))
            result[kind] = _unique(normalized, key)
            result["states"][kind] = "complete_window"
        except (SupplyError, AttributeError, TypeError) as exc:
            result["states"][kind] = "failed"
            result["errors"][kind] = str(exc) if isinstance(exc, SupplyError) else "API_SHAPE_ERROR"
    for sku in skus:
        try:
            data = call(PRODUCT_PATH, {"sku": sku}).get("data")
            if not isinstance(data, dict) or data.get("sku") != sku:
                raise SupplyError("PRODUCT_IDENTITY_MISMATCH")
            quotes = []
            for supplier in data.get("supplier_quote") or []:
                for quote in supplier.get("quotes") or []:
                    values = [_qty(p.get("moq")) for p in quote.get("step_prices") or []]
                    quotes.append({"supplier_id": supplier.get("supplier_id"), "quote_id": quote.get("id"), "moqs": values})
            # Tier prices contain several thresholds. Their minimum is the quote's MOQ;
            # supplier/quote ambiguity is retained instead of choosing a cheap supplier.
            minima = {min(q["moqs"]) for q in quotes if q["moqs"] and all(v is not None for v in q["moqs"])}
            valid = len(minima) == 1 and len(quotes) > 0 and all(q["moqs"] and None not in q["moqs"] for q in quotes)
            result["products"].append({"sku": sku, "carton_qty": _qty(data.get("cg_box_pcs")), "quotes": quotes,
                "moq": next(iter(minima)) if valid else None, "moq_state": "consistent" if valid else "missing_or_ambiguous",
                "components": [{"sku": i.get("sku"), "quantity": _qty(i.get("quantity"))} for i in data.get("combo_product_list") or []], "state": "verified"})
        except (SupplyError, AttributeError, TypeError) as exc:
            result["products"].append({"sku": sku, "state": "failed", "error": str(exc) if isinstance(exc, SupplyError) else "API_SHAPE_ERROR"})
    result["states"]["products"] = "partial" if any(p["state"] == "failed" for p in result["products"]) else "complete_window"
    result.update(calls=calls, audit=audit)
    return result


def apply_details(snapshot, details, *, allowed_sids):
    """Attach facts by exact shop/SKU; never allocate API facts by sales share."""
    if details.get("schema") != SCHEMA or details.get("as_of") != snapshot.get("metadata", {}).get("asOf"):
        raise SupplyError("DETAILS_DATE_OR_SCHEMA_MISMATCH")
    allowed = {str(s) for s in allowed_sids}
    result = copy.deepcopy(snapshot)
    if any(str(r.get("storeId")) not in allowed for r in result["records"]):
        raise SupplyError("SNAPSHOT_SCOPE_DENIED")
    for name in ("purchases", "receipts", "shipments"):
        if any(str(r.get("sid")) not in allowed for r in details[name]):
            raise SupplyError("DETAILS_SCOPE_DENIED")
    purchases = _unique(details["purchases"], lambda p: (p["order_sn"], p["item_id"]))
    receipts = _unique(details["receipts"], lambda r: (r["order_sn"], r["item_id"]))
    purchases = copy.deepcopy(purchases)
    receipts = copy.deepcopy(receipts)
    purchase_index = {(p["order_sn"], p["item_id"]): p for p in purchases}
    for receipt in receipts:
        purchase = purchase_index.get((receipt["purchase_order"], receipt["purchase_item_id"]))
        receipt["join_state"] = "outside_window_or_missing"
        if purchase:
            receipt["join_state"] = "matched" if (receipt["sid"], receipt["sku"]) == (purchase["sid"], purchase["sku"]) else "shop_or_sku_conflict"
    for purchase in purchases:
        related = [r for r in receipts if (r["purchase_order"], r["purchase_item_id"]) == (purchase["order_sn"], purchase["item_id"])]
        matched = [r for r in related if r["join_state"] == "matched" and r["status"] == "40" and r["actual_time"]
                   and _date(r["actual_time"]) <= details["as_of"] and r["actual_qty"] is not None]
        receipts_complete = details["states"]["receipts"] == "complete_window" and len(matched) == len(related)
        purchase["actual_received_in_window"] = sum(r["actual_qty"] for r in matched) if receipts_complete else None
        purchase["actual_times"] = sorted({r["actual_time"] for r in matched})
        # Pending is the official balance, not ordered minus this window's receipts.
        # Returns/exchanges and disagreements need reconciliation before use.
        eligible = (receipts_complete and purchase["status"] == "2" and purchase["arrival_status"] in {"1", "2"}
                    and purchase["deleted"] == "0" and purchase["returned_qty"] == 0
                    and purchase["exchanged_qty"] == 0 and purchase["pending_qty"] is not None
                    and purchase["ordered_qty"] is not None
                    and purchase["pending_qty"] + purchase["actual_received_in_window"] <= purchase["ordered_qty"]
                    and all(r["join_state"] == "matched" for r in related))
        not_ordered = purchase["status"] in {"1", "3", "121", "122"}
        purchase["remaining_qty"] = purchase["pending_qty"] if eligible else 0 if not_ordered or purchase["status"] in {"9", "-1", "124"} or purchase["deleted"] == "1" else None
        purchase["balance_state"] = "verified" if eligible else "not_ordered" if not_ordered else "closed" if purchase["remaining_qty"] == 0 else "needs_review"
    owners = Counter((str(r["storeId"]), sku) for r in result["records"] for sku in set(r.get("skus") or [r.get("sku")]) if sku)
    products = {p["sku"]: p for p in details["products"]}
    for record in result["records"]:
        sid = str(record["storeId"])
        skus = set(record.get("skus") or [record.get("sku")])
        facts = [products[s] for s in sorted(skus) if s in products]
        components = {c["sku"] for p in facts for c in p.get("components", []) if c.get("sku")}
        direct = [p for p in purchases if p["sid"] == sid and p["sku"] in skus]
        actual = [r for r in receipts if r["sid"] == sid and r["sku"] in skus | components]
        unique_owner = len(skus) == 1 and all(owners[sid, s] == 1 for s in skus)
        record["purchaseEvidence"] = {"window_start": details["window_start"], "window_end": details["as_of"],
            "state": details["states"]["purchases"], "allocation": "exact_shop_sku" if unique_owner else "shared_sku_reference_only",
            "dataset_states": copy.deepcopy(details["states"]),
            "items": direct, "component_items": [p for p in purchases if p["sid"] == sid and p["sku"] in components - skus],
            "receipts": actual, "product_rules": facts}
        known_balances = all(p["remaining_qty"] is not None for p in direct)
        scoped_balance = sum(p["remaining_qty"] for p in direct) if unique_owner and known_balances and details["states"]["purchases"] == "complete_window" else None
        record.setdefault("procurementMcpReference", record.get("procurementOpen"))
        record["procurementOpen"] = scoped_balance
        record.setdefault("inventoryLayers", {})["procurementOpen"] = scoped_balance
        record["procurementBalanceScope"] = "API窗口内店铺SKU；非全历史余额"
        gap = "采购余额仅覆盖API查询窗口；共享SKU或异常余额不分摊，历史未结须另行核对"
        if gap not in record.setdefault("dataGaps", []):
            record["dataGaps"].append(gap)
        # Preserve current MCP inventory. This is a dated ledger, not a replacement
        # for the current full balance. Do not feed domestic ETA into the FBA curve.
        record["procurementLots"] = [{"id": f"{p['order_sn']}:{p['item_id']}", "qty": p["remaining_qty"], "date": p["expected_date"]}
            for p in direct if unique_owner and p["balance_state"] == "verified" and p["remaining_qty"] > 0
            and p["expected_date"] and p["expected_date"] >= details["as_of"]]
        record["fbaShipmentEvidence"] = [r for r in details["shipments"] if r["sid"] == sid and r["asin"] == record["asin"]]
        if len(facts) == 1 and len(skus) == 1 and facts[0]["state"] == "verified":
            rule = facts[0]
            if not record.get("cartonQty") or record.get("cartonSource") == "领星 API 产品单箱数量":
                record["cartonQty"], record["cartonSource"] = rule["carton_qty"] or 0, "领星 API 产品单箱数量"
            if not record.get("moq") or record.get("moqSource") == "领星 API 产品报价":
                record["moqSource"] = "领星 API 产品报价"
                if rule["moq"] is not None and rule["moq"] > 0:
                    record["moq"] = rule["moq"]
                else:
                    record.pop("moq", None)
        else:
            # Failed or no-longer-unambiguous refresh must not silently keep an
            # earlier API default as if it belonged to the current source batch.
            if record.get("cartonSource") == "领星 API 产品单箱数量":
                record["cartonQty"] = 0
            if record.get("moqSource") == "领星 API 产品报价":
                record.pop("moq", None)
        record["evidence"] = [e for e in record.get("evidence", []) if e.get("stage") != "API采购与收货"]
        record["evidence"].append({"stage": "API采购与收货", "source": "领星 OpenAPI / 店铺 + SKU + 单据行",
            "fact": f"{len(direct)} 行采购，{len(actual)} 行实际收货；收货不重复增加库存；组件不相加为成品；统计窗口 {details['window_start']} 至 {details['as_of']}"})
    result["metadata"]["supplyDetails"] = {k: copy.deepcopy(details[k]) for k in ("schema", "generated_at", "window_start", "as_of", "states", "errors")}
    # One canonical ledger for aggregation, not a sum over ASIN reference drawers.
    result["metadata"]["supplyDetails"]["ledger"] = {"purchases": purchases, "receipts": receipts}
    return result


def reconcile_fba(supply, details, *, allowed_sids):
    """Reconcile before ETA aggregation so totals and curves share one quantity."""
    allowed = {str(s) for s in allowed_sids}
    if details.get("schema") != SCHEMA or supply.get("as_of") != details.get("as_of"):
        raise SupplyError("DETAILS_DATE_OR_SCHEMA_MISMATCH")
    if any(str(r.get("sid")) not in allowed for r in details["shipments"]):
        raise SupplyError("DETAILS_SCOPE_DENIED")
    result = copy.deepcopy(supply)
    for record in result["records"]:
        for item in record["items"]:
            lines = [r for r in details["shipments"] if (r["sid"], r["asin"], r["shipment_id"]) == (record["sid"], record["asin"], item["shipment_id"])]
            if not lines:
                if item["state"] == "verified":
                    item["state"] = "missing_fba_contents"
                continue
            item["fba_status"] = sorted({r["status"] for r in lines})
            item["source_quantity"] = item.get("source_quantity", item["quantity"])
            item["fba_contents"] = lines
            if all(r["status"] in {"WORKING", "READY_TO_SHIP"} and r["local_shipped_qty"] == 0 for r in lines):
                item["state"] = "waiting_pick" if item["state"] == "waiting_pick" else "waiting_dispatch"
            elif all(r["status"] in {"CLOSED", "CANCELLED", "DELETED"} for r in lines):
                item["state"] = "completed"
            elif all(r["local_shipped_qty"] is not None and r["received_qty"] is not None for r in lines):
                physical = sum(max(0, r["local_shipped_qty"] - r["received_qty"]) for r in lines)
                item["quantity"] = min(item["source_quantity"], physical)
                if any(r["received_qty"] > r["local_shipped_qty"] for r in lines) or (physical == 0 and item["source_quantity"] > 0):
                    item["state"] = "unknown_physical_quantity"
            elif item["state"] == "verified":
                item["state"] = "unknown_physical_quantity"
        if record["state"] != "failed":
            record["state"] = "partial" if any(i["state"] != "verified" for i in record["items"]) else "verified"
    return result
