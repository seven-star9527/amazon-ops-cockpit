"""Adapt the installed advertising diagnosis Skill to B's immutable action model.

The specialist Skill owns thresholds, candidate classification, processed-state
checks, and product-level Exact aggregation. B owns source collection, review,
and its narrower SP-negative-only remote execution boundary.
"""

from __future__ import annotations

from functools import lru_cache
from hashlib import sha256
import importlib
import os
from pathlib import Path
import sys


ACTION_KINDS = {
    "negative_keyword_candidate": "negative",
    "asin_negative_candidate": "negative_asin",
    "exact_keyword_candidate": "exact",
    "asin_exact_candidate": "exact",
}
REASON_LABELS = {
    "zero_order_spend_reached_reference_cpa": "无单点击达到门槛，花费达到同组参考 CPA",
    "asin_zero_order_spend_reached_reference_cpa": "ASIN 定向无单，花费达到同组参考 CPA",
    "non_exact_converted_within_target_acos": "非精准词至少 2 单，ACOS 不高于 30%",
    "asin_non_exact_converted_within_target_acos": "非精准商品定向至少 2 单，ACOS 不高于 30%",
    "non_exact_converted_near_target_acos": "ACOS 介于 30%–33%，先观察",
    "acos_above_target_buffer": "ACOS 高于 33%，先复核降价",
    "asin_acos_above_target_buffer": "ASIN 定向 ACOS 高于 33%，先复核降价",
    "zero_order_click_threshold": "无单点击达到门槛，但花费或参考 CPA 证据不足",
    "asin_target_zero_order_clicks": "ASIN 定向无单点击达到门槛，仍需更多花费证据",
}


@lru_cache(maxsize=1)
def _specialist():
    override = os.environ.get("AMAZON_ADS_SKILL_DIR")
    location = (Path(override) if override else
                Path(__file__).resolve().parents[2] / "vendor" / "amazon_ads_specialist")
    if location.name != "scripts" and (location / "scripts").is_dir():
        location /= "scripts"
    required = (location / "ads_rule_engine.py", location / "dashboard_views.py")
    if not all(path.is_file() for path in required):
        raise RuntimeError(f"advertising specialist Skill is missing: {location}")
    if str(location) not in sys.path:
        sys.path.insert(0, str(location))
    rules = importlib.import_module("ads_rule_engine")
    views = importlib.import_module("dashboard_views")
    for name in ("analyze_search_terms", "AdsRuleConfig"):
        if not hasattr(rules, name):
            raise RuntimeError(f"advertising specialist missing {name}")
    for name in ("build_action_scopes", "enrich_exact_scopes"):
        if not hasattr(views, name):
            raise RuntimeError(f"advertising specialist missing {name}")
    digest = sha256(b"".join(path.read_bytes() for path in required)).hexdigest()
    return rules, views, digest


def specialist_fingerprint() -> str:
    """Record the exact installed specialist code used for this snapshot."""
    return _specialist()[2]


def _candidate_rows(rows: list[dict]) -> list[dict]:
    """Pass one verified search-term record to the specialist, without B hints."""
    result = []
    for row in rows:
        if not row.get("query") or not row.get("campaign_id") or not row.get("ad_group_id"):
            continue
        item = dict(row)
        item["spends"] = row.get("spends", row.get("spend", 0))
        item["related_asins"] = list(row.get("related_asins") or [])
        negatives = row.get("st_negatives")
        if isinstance(negatives, list):
            # Lingxing marks an existing search-term negative as 已否定. The
            # specialist keyword matcher recognizes 精准否定; translate only
            # this explicit ad-group status, never a free-text hint.
            item["st_negatives"] = [
                {**entry, "match_type": "精准否定"}
                if isinstance(entry, dict) and str(entry.get("match_type") or "") == "已否定"
                and str(entry.get("ng_level") or "") == "ad_group" else entry
                for entry in negatives
            ]
        # Only current search-term negatives may prove this exact object is processed.
        raw = dict(row.get("raw") or {})
        raw.pop("kw_negatives", None)
        raw.pop("target_negatives", None)
        raw.pop("product_negatives", None)
        if isinstance(negatives, list):
            raw["st_negatives"] = item["st_negatives"]
        item["raw"] = raw
        item.pop("kw_negatives", None)
        item.pop("target_negatives", None)
        item.pop("product_negatives", None)
        result.append(item)
    return result


def diagnose_search_terms(rows: list[dict], *, target_acos: float = .30,
                          negative_clicks: int = 10, exact_orders: int = 2,
                          source_complete: bool = True) -> list[dict]:
    """Return B actions from the updated specialist's pure rule/view functions."""
    rules, views, _ = _specialist()
    terms = _candidate_rows(rows)
    config = rules.AdsRuleConfig(target_acos=target_acos, negative_clicks=negative_clicks,
                                 exact_orders=exact_orders)
    classified = rules.analyze_search_terms(
        [item for item in terms if views.is_ad_scope_active(item)], config
    )["actions"]
    scopes = views.build_action_scopes(classified)
    scopes = views.enrich_exact_scopes(scopes, terms)
    actions = []
    for scope in scopes:
        kind = ACTION_KINDS.get(scope["action_type"], "observe")
        affected = sorted({str(asin).upper() for asin in scope.get("related_asins", []) if asin})
        processed = str(scope.get("processed_status") or "")
        plan = scope.get("exact_plan") or {}
        blocked = str(plan.get("blocked_reason") or "")
        if kind == "exact" and plan.get("target_required"):
            blocked = "missing_single_product_destination"
        if not affected:
            blocked = "unmapped_promoted_asin"
        if not source_complete:
            blocked = "incomplete_source_coverage"
        reviewable = bool(kind != "observe" and not processed and not blocked and
                          scope.get("sponsored_type") == "sp" and
                          all(scope.get(name) for name in ("profile_id", "campaign_id", "ad_group_id")))
        executable = bool(reviewable and kind in {"negative", "negative_asin"})
        reason = REASON_LABELS.get(scope.get("reason_code"), "广告搜索词需人工观察")
        if processed == "already_exact_negative":
            reason += "；当前同组已有精准否定"
        elif processed == "already_exact_running":
            reason += "；该产品已有在投精准目标"
        elif blocked:
            reason += f"；待补证据：{blocked}"
        action = {
            "action_key": scope["action_key"], "kind": kind,
            "action_type": scope["action_type"], "reason_code": scope.get("reason_code"),
            "profile_id": scope.get("profile_id", ""), "sponsored_type": scope.get("sponsored_type", ""),
            "campaign_id": scope.get("campaign_id", ""), "campaign_name": scope.get("campaign_name", ""),
            "ad_group_id": scope.get("ad_group_id", ""), "ad_group_name": scope.get("ad_group_name", ""),
            "query": scope.get("query", ""), "normalized_keyword": str(scope.get("query") or "").casefold(),
            "clicks": scope.get("clicks", 0), "spend": scope.get("spends", 0),
            "impressions": scope.get("impressions", 0), "orders": scope.get("orders", 0),
            "sales": scope.get("sales", 0), "acos": scope.get("acos"),
            "cpc": scope.get("cpc"), "cvr": scope.get("cvr"), "reference_cpa": scope.get("reference_cpa"),
            "match_types": sorted({str(source.get("target_match_type") or source.get("match_type") or "")
                                   for source in scope.get("sources", [])}),
            "record_ids": scope.get("source_record_ids", []), "affected_asins": affected,
            "shared_group": scope.get("relation_type") == "shared_group",
            "reason": reason, "reviewable": reviewable, "executable": executable,
            "processed_status": processed, "blocked_reason": blocked,
            "existing_exact": bool(scope.get("already_exact_running")),
            "existing_exact_matches": scope.get("existing_exact_matches", []) if kind == "exact" else [],
            "existing_negative": bool(scope.get("already_exact_negative")),
            "suggested_bid": plan.get("exact_bid"), "exact_plan": plan if kind == "exact" else None,
            "source_scopes": scope.get("source_scopes", []),
            "source_rows": scope.get("sources", []), "source_count": scope.get("source_count", 0),
        }
        actions.append(action)
    return sorted(actions, key=lambda item: (not item["reviewable"], bool(item["processed_status"]),
                                              -float(item["spend"] or 0), item["query"].casefold()))
