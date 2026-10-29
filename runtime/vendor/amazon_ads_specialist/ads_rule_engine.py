from __future__ import annotations

from collections import OrderedDict, defaultdict
from dataclasses import asdict, dataclass
import re
from typing import Any, Iterable


@dataclass(frozen=True)
class AdsRuleConfig:
    target_acos: float = 0.30
    negative_clicks: int = 10
    exact_orders: int = 2
    bid_down_clicks: int = 20
    bid_down_buffer: float = 0.10


WRITE_TOOL_IDS = {
    "advertising_add_negative_keywords",
    "advertising_add_negative_targets",
    "advertising_sp_add_keywords",
    "post_targets_sp",
    "post_targets",
    "put_targets_sp",
    "put_targets",
}

METRIC_FIELDS = ("impressions", "clicks", "orders", "spends", "sales")
EXACT_OR_PRODUCT_MATCHES = {
    "exact", "keyword_exact", "exactmatch", "asin", "asinsameas",
    "product", "product_exact", "productexact",
}


def _num(row: dict[str, Any], name: str) -> float:
    try:
        return float(row.get(name) or 0)
    except (TypeError, ValueError):
        return 0.0


def _text(value: Any) -> str:
    return str(value or "").strip()


def _decision_key(row: dict[str, Any]) -> tuple[str, str, str, str, str]:
    return (
        _text(row.get("profile_id")),
        _text(row.get("sponsored_type")).lower(),
        _text(row.get("campaign_id")),
        _text(row.get("ad_group_id")),
        _text(row.get("query")).casefold(),
    )


def _relation_type(asins: list[str], seen: set[str]) -> str:
    if "shared_group" in seen or len(asins) > 1:
        return "shared_group"
    if asins:
        return "single_product"
    return "unmapped"


def _aggregate_decision_rows(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse keyword/target sources into the ad-group action scope before rules."""
    grouped: OrderedDict[tuple[str, str, str, str, str], list[dict[str, Any]]] = OrderedDict()
    for row in rows:
        grouped.setdefault(_decision_key(row), []).append(row)

    result: list[dict[str, Any]] = []
    for source_rows in grouped.values():
        first = source_rows[0]
        item = dict(first)
        for name in METRIC_FIELDS:
            item[name] = sum(_num(row, name) for row in source_rows)
        orders, spends, sales = item["orders"], item["spends"], item["sales"]
        item["cpa"] = spends / orders if orders else None
        item["acos"] = spends / sales if sales else None
        item["related_asins"] = sorted({
            _text(asin).upper()
            for row in source_rows
            for asin in row.get("related_asins", [])
            if _text(asin)
        })
        relations = {_text(row.get("relation_type")) for row in source_rows}
        item["relation_type"] = _relation_type(item["related_asins"], relations)
        match_types = list(dict.fromkeys(
            _text(row.get("target_match_type") or row.get("match_type")).lower()
            for row in source_rows
            if _text(row.get("target_match_type") or row.get("match_type"))
        ))
        item["target_match_types"] = match_types
        item["target_match_type"] = match_types[0] if len(match_types) == 1 else ("mixed" if match_types else "")
        item["source_record_ids"] = list(dict.fromkeys(
            _text(row.get("record_id")) for row in source_rows if _text(row.get("record_id"))
        ))
        item["source_record_id"] = item["source_record_ids"][0] if item["source_record_ids"] else ""
        item["source_rows"] = [dict(row) for row in source_rows]
        item["source_count"] = len(source_rows)
        result.append(item)
    return result


def _reference_cpa(rows: Iterable[dict[str, Any]], target_acos: float) -> float | None:
    sales = sum(_num(row, "sales") for row in rows if _num(row, "orders") > 0)
    orders = sum(_num(row, "orders") for row in rows if _num(row, "orders") > 0)
    if not orders:
        return None
    return sales / orders * target_acos


def _action_key(row: dict[str, Any], action_type: str) -> str:
    parts = (
        row.get("profile_id"), row.get("sponsored_type"), row.get("campaign_id"),
        row.get("ad_group_id"), row.get("query"), action_type,
    )
    return "|".join(_text(value).casefold() for value in parts)


def _is_asin_target(value: Any) -> bool:
    """Only Amazon's ten-character ASIN shape is an ASIN-target query."""
    normalized = _text(value).upper()
    return bool(re.fullmatch(r"B[0-9A-Z]{9}", normalized)) and any(character.isdigit() for character in normalized)


def _has_existing_exact_or_product_target(row: dict[str, Any]) -> bool:
    matches = row.get("target_match_types") or [row.get("target_match_type") or row.get("match_type")]
    return any(_text(value).lower() in EXACT_OR_PRODUCT_MATCHES for value in matches)


def _action_base(row: dict[str, Any], reference_cpa: float | None) -> dict[str, Any]:
    return {
        "action_key": "",
        "profile_id": row.get("profile_id", ""),
        "shop": row.get("shop", ""),
        "campaign_id": row.get("campaign_id", ""),
        "campaign_name": row.get("campaign_name", ""),
        "ad_group_id": row.get("ad_group_id", ""),
        "ad_group_name": row.get("ad_group_name", ""),
        "query": row.get("query", ""),
        "keyword_id": "",
        "target_id": "",
        "sponsored_type": row.get("sponsored_type", ""),
        "target_match_type": row.get("target_match_type", ""),
        "target_match_types": list(row.get("target_match_types", [])),
        "orders": _num(row, "orders"),
        "clicks": _num(row, "clicks"),
        "impressions": _num(row, "impressions"),
        "spends": _num(row, "spends"),
        "sales": _num(row, "sales"),
        "cpa": row.get("cpa"),
        "acos": row.get("acos"),
        "reference_cpa": reference_cpa,
        "relation_type": row.get("relation_type", "unmapped"),
        "related_asins": list(row.get("related_asins", [])),
        "source_record_id": row.get("source_record_id", ""),
        "source_record_ids": list(row.get("source_record_ids", [])),
        "source_count": int(row.get("source_count") or 1),
        "source_rows": list(row.get("source_rows", [])),
        "source_row": {key: value for key, value in row.items() if key != "source_rows"},
    }


def _append_action(actions: list[dict[str, Any]], row: dict[str, Any], base: dict[str, Any], action_type: str, reason_code: str) -> None:
    action = dict(base)
    action["action_type"] = action_type
    action["reason_code"] = reason_code
    action["action_key"] = _action_key(row, action_type)
    actions.append(action)


def analyze_search_terms(rows: list[dict[str, Any]], config: AdsRuleConfig | None = None) -> dict[str, Any]:
    cfg = config or AdsRuleConfig()
    decision_rows = _aggregate_decision_rows(rows)
    reference_groups: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in decision_rows:
        key = (
            _text(row.get("profile_id")), _text(row.get("sponsored_type")).lower(),
            _text(row.get("campaign_id")), _text(row.get("ad_group_id")),
        )
        reference_groups[key].append(row)
    references = {key: _reference_cpa(value, cfg.target_acos) for key, value in reference_groups.items()}

    actions: list[dict[str, Any]] = []
    buffered_target = cfg.target_acos * (1 + cfg.bid_down_buffer)
    for row in decision_rows:
        orders = _num(row, "orders")
        clicks = _num(row, "clicks")
        spend = _num(row, "spends")
        acos = row.get("acos")
        group_key = (
            _text(row.get("profile_id")), _text(row.get("sponsored_type")).lower(),
            _text(row.get("campaign_id")), _text(row.get("ad_group_id")),
        )
        reference_cpa = references.get(group_key)
        base = _action_base(row, reference_cpa)

        if _is_asin_target(row.get("query")):
            if orders == 0 and clicks >= cfg.negative_clicks:
                if reference_cpa is not None and spend >= reference_cpa:
                    _append_action(actions, row, base, "asin_negative_candidate", "asin_zero_order_spend_reached_reference_cpa")
                else:
                    _append_action(actions, row, base, "asin_negative_observe", "asin_target_zero_order_clicks")
            elif orders >= cfg.exact_orders and not _has_existing_exact_or_product_target(row):
                if acos is not None and acos <= cfg.target_acos:
                    _append_action(actions, row, base, "asin_exact_candidate", "asin_non_exact_converted_within_target_acos")
                elif acos is not None and clicks >= cfg.bid_down_clicks and acos > buffered_target:
                    _append_action(actions, row, base, "bid_down_observe", "asin_acos_above_target_buffer")
            elif orders > 0 and acos is not None and clicks >= cfg.bid_down_clicks and acos > buffered_target:
                _append_action(actions, row, base, "bid_down_observe", "asin_acos_above_target_buffer")
            continue

        if orders == 0:
            if clicks >= cfg.negative_clicks:
                if reference_cpa is not None and spend >= reference_cpa:
                    _append_action(actions, row, base, "negative_keyword_candidate", "zero_order_spend_reached_reference_cpa")
                else:
                    _append_action(actions, row, base, "negative_keyword_observe", "zero_order_click_threshold")
            continue

        existing_exact = _has_existing_exact_or_product_target(row)
        if orders >= cfg.exact_orders and not existing_exact:
            if acos is not None and acos <= cfg.target_acos:
                _append_action(actions, row, base, "exact_keyword_candidate", "non_exact_converted_within_target_acos")
            elif acos is not None and acos <= buffered_target:
                _append_action(actions, row, base, "exact_keyword_observe", "non_exact_converted_near_target_acos")
            elif acos is not None and clicks >= cfg.bid_down_clicks:
                _append_action(actions, row, base, "bid_down_observe", "acos_above_target_buffer")
            else:
                _append_action(actions, row, base, "exact_keyword_observe", "non_exact_converted_efficiency_unconfirmed")
            continue

        if acos is not None and clicks >= cfg.bid_down_clicks and acos > buffered_target:
            _append_action(actions, row, base, "bid_down_observe", "acos_above_target_buffer")

    return {
        "config": asdict(cfg),
        "actions": actions,
        "reference_cpa": {"|".join(key): value for key, value in references.items()},
        "decision_scope_count": len(decision_rows),
    }
