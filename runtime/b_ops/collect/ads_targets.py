"""Read-only SP keyword-target performance; a report is not a full target catalog."""

from __future__ import annotations

from b_ops.collect.lingxing import LingxingError, extract_data
from b_ops.model.snapshot import number
from b_ops.model.storage import normalize_keyword


def normalize_keyword_target(row: dict, profile_id: str) -> dict:
    bid = number(row.get("bid"))
    default_bid = number(row.get("default_bid"))
    bidding = row.get("bidding") if isinstance(row.get("bidding"), dict) else {}
    adjustments = {}
    for item in bidding.get("adjustments") or []:
        if isinstance(item, dict) and item.get("predicate"):
            value = number(item.get("percentage"))
            if value is not None:
                adjustments[str(item["predicate"])] = value
    return {
        "profile_id": str(row.get("profile_id") or profile_id),
        "sponsored_type": str(row.get("sponsored_type") or "").lower(),
        "campaign_id": str(row.get("campaign_id") or ""),
        "campaign_name": str(row.get("campaign_name") or ""),
        "ad_group_id": str(row.get("ad_group_id") or ""),
        "ad_group_name": str(row.get("ad_group_name") or ""),
        "target_id": str(row.get("keyword_id") or ""),
        "keyword": str(row.get("keyword_text") or row.get("targeting_text") or "").strip(),
        "normalized_keyword": normalize_keyword(str(row.get("keyword_text") or row.get("targeting_text") or "")),
        "match_type": str(row.get("match_type") or "").lower(),
        "target_state": str(row.get("state") or "").lower(),
        "campaign_state": str(row.get("campaign_state") or "").lower(),
        "ad_group_state": str(row.get("ad_group_state") or "").lower(),
        "bid": bid, "default_bid": default_bid,
        "base_bid": bid if bid is not None else default_bid,
        "bid_source": "target" if bid is not None else "group_default" if default_bid is not None else "unknown",
        "bidding_strategy": str(bidding.get("strategy") or ""),
        "placement_adjustments": adjustments,
        "audience_adjustments": bidding.get("shopperCohortBidding"),
        "adjustments_bid_map": row.get("adjustmentsBidMap"),
        "is_apply_time": row.get("is_apply_time"),
        "budget": number(row.get("budget")),
        "budget_type": row.get("budget_type"),
        "impressions": number(row.get("impressions")),
        "clicks": number(row.get("clicks")),
        "spend": number(row.get("spends")),
        "orders": number(row.get("orders")),
        "sales": number(row.get("sales")),
    }


def _reported_total(value) -> int | None:
    if not isinstance(value, dict):
        return None
    for field in ("recordsFiltered", "total", "count"):
        item = value.get(field)
        if isinstance(item, (int, float)):
            return int(item)
    for item in value.values():
        result = _reported_total(item)
        if result is not None:
            return result
    return None


def collect_keyword_target_report(client, profile_id: str, start: str, end: str,
                                  *, page_size: int = 500, max_pages: int = 200) -> tuple[list[dict], dict]:
    """Collect target-ID report rows; absence does not prove the target does not exist."""
    result, seen = [], set()
    expected = None
    for page in range(1, max_pages + 1):
        response = client.read("ad_campaign_keyword_report", {
            "report_date": f"{start} - {end}", "profile_ids": [str(profile_id)],
            "sponsored_type": ["sp"], "group_type": "keyword_id",
            "page": page, "length": page_size, "sort_field": "spends", "sort_type": "desc",
            "with_ring": 0,
        })
        raw = extract_data(response)
        rows = raw if isinstance(raw, list) else raw.get("data") or raw.get("list") if isinstance(raw, dict) else None
        if not isinstance(rows, list):
            raise LingxingError("keyword target report page shape mismatch")
        total = _reported_total(response)
        if total is not None:
            if expected is not None and total != expected:
                raise LingxingError("keyword target report total changed")
            expected = total
        detail = [row for row in rows if isinstance(row, dict) and row.get("keyword_id")]
        for row in detail:
            item = normalize_keyword_target(row, profile_id)
            if item["sponsored_type"] != "sp" or not item["target_id"]:
                continue
            identity = (item["profile_id"], item["campaign_id"], item["ad_group_id"], item["target_id"])
            if identity in seen:
                raise LingxingError("duplicate keyword target across pages")
            seen.add(identity)
            result.append(item)
        if (expected is not None and len(result) >= expected) or len(detail) < page_size:
            break
    else:
        raise LingxingError("keyword target report page bound exceeded")
    if expected is not None and len(result) != expected:
        raise LingxingError(f"keyword target report incomplete {len(result)}/{expected}")
    return result, {"state": "verified_performance", "rows": len(result),
                    "reported_total": expected, "catalog_complete": False,
                    "period": [start, end]}


def target_evidence_by_product(targets: list[dict], group_links: dict,
                               profile_to_sid: dict[str, str], products: dict[str, dict]) -> dict:
    """Project one group target into affected child views without attributing its totals."""
    product_index = {(item["sid"], item["asin"]): item["key"] for item in products.values()}
    result: dict[str, dict[str, list[dict]]] = {}
    for target in targets:
        profile = target["profile_id"]
        sid = profile_to_sid.get(profile)
        asins = sorted(str(value).upper() for value in group_links.get(
            (profile, target["ad_group_id"]), set()))
        if not sid or not target["normalized_keyword"]:
            continue
        evidence = {**target, "affected_asins": asins, "shared_group": len(asins) > 1,
                    "attribution": "group_shared" if len(asins) > 1 else "group_only"}
        for asin in asins:
            product_key = product_index.get((sid, asin))
            if product_key:
                result.setdefault(product_key, {}).setdefault(target["normalized_keyword"], []).append(evidence)
    return result


def collect_targets_by_profile(client, profile_to_sid: dict[str, str],
                               start: str, end: str) -> tuple[list[dict], dict[str, dict]]:
    all_rows, statuses = [], {}
    for profile_id in profile_to_sid:
        try:
            rows, status = collect_keyword_target_report(client, profile_id, start, end)
            all_rows.extend(rows)
            statuses[profile_id] = status
        except Exception as exc:
            statuses[profile_id] = {"state": "unavailable", "error_type": type(exc).__name__,
                                    "catalog_complete": False}
    return all_rows, statuses


def collect_campaign_settings(client, profile_id: str, start: str, end: str,
                              *, page_size: int = 500, max_pages: int = 200) -> tuple[list[dict], dict]:
    """Read campaign budget/strategy in the same period as target performance."""
    result, seen = [], set()
    detail_count = 0
    expected = None
    for page in range(1, max_pages + 1):
        response = client.read("ad_campaign_report", {
            "report_date": f"{start} - {end}", "profile_ids": [str(profile_id)],
            "sponsored_type": ["sp"], "page": page, "length": page_size,
            "sort_field": "spends", "sort_type": "desc", "with_ring": 0,
        })
        raw = extract_data(response)
        rows = raw if isinstance(raw, list) else (
            raw.get("data") or raw.get("list") if isinstance(raw, dict) else None)
        if not isinstance(rows, list):
            raise LingxingError("campaign report page shape mismatch")
        total = _reported_total(response)
        if total is not None:
            if expected is not None and total != expected:
                raise LingxingError("campaign report total changed")
            expected = total
        detail = [row for row in rows if isinstance(row, dict) and row.get("campaign_id")]
        detail_count += len(detail)
        for row in detail:
            if str(row.get("sponsored_type") or "").lower() != "sp":
                continue
            identity = (str(row.get("profile_id") or profile_id), str(row["campaign_id"]))
            if identity in seen:
                raise LingxingError("duplicate campaign across pages")
            seen.add(identity)
            bidding = row.get("bidding") if isinstance(row.get("bidding"), dict) else {}
            adjustments = {str(item["predicate"]): number(item.get("percentage"))
                           for item in bidding.get("adjustments") or []
                           if isinstance(item, dict) and item.get("predicate")}
            result.append({"profile_id": identity[0], "campaign_id": identity[1],
                           "budget": number(row.get("daily_budget") or row.get("budget")),
                           "budget_type": row.get("budget_type"),
                           "bidding_strategy": bidding.get("strategy"),
                           "placement_adjustments": adjustments,
                           "is_apply_time": row.get("is_apply_time"),
                           "spend": number(row.get("spends"))})
        if (expected is not None and detail_count >= expected) or len(detail) < page_size:
            break
    else:
        raise LingxingError("campaign report page bound exceeded")
    if expected is not None and detail_count != expected:
        raise LingxingError(f"campaign report incomplete {detail_count}/{expected}")
    return result, {"state": "verified_performance", "rows": len(result), "reported_total": expected,
                    "period": [start, end]}


def enrich_targets_with_campaigns(targets: list[dict], campaigns: list[dict]) -> list[dict]:
    by_key = {(row["profile_id"], row["campaign_id"]): row for row in campaigns}
    result = []
    for target in targets:
        row = dict(target)
        campaign = by_key.get((row["profile_id"], row["campaign_id"]))
        if campaign:
            row["budget"] = campaign.get("budget")
            row["budget_type"] = campaign.get("budget_type")
            row["campaign_spend"] = campaign.get("spend")
            row["bidding_strategy"] = campaign.get("bidding_strategy") or row.get("bidding_strategy")
            row["placement_adjustments"] = campaign.get("placement_adjustments") or row.get("placement_adjustments")
            row["is_apply_time"] = campaign.get("is_apply_time")
            row["campaign_settings_state"] = "verified_performance"
        else:
            row["campaign_settings_state"] = "not_in_report"
        result.append(row)
    return result
