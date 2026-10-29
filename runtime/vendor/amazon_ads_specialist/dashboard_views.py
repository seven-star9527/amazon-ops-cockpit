"""Pure view-model helpers for the two-page operator dashboard."""

from __future__ import annotations

from collections import OrderedDict, defaultdict
import json
from typing import Any, Iterable

from root_aggregator import canonical_asin
from root_parser import split_words


METRIC_FIELDS = ("impressions", "clicks", "orders", "spends", "sales")
ACTIVE_STATES = {"", "enabled", "active", "live", "1", "在售"}
ACTIVE_LISTING_STATES = {"enabled", "active", "live", "1", "在售", "onsale", "on_sale"}
TRUE_VALUES = {"1", "true", "yes", "是"}
NEGATIVE_FIELDS = ("st_negatives", "kw_negatives", "target_negatives", "product_negatives")
EXACT_ACTION_TYPES = {"exact_keyword_candidate", "asin_exact_candidate"}
BID_ACTION_TYPES = {"bid_decrease_candidate", "bid_increase_candidate"}
KEYWORD_EXACT_MATCHES = {"exact", "exactmatch", "keyword_exact", "keywordexact", "精准", "精确"}
PRODUCT_EXACT_MATCHES = {
    "asin", "asinsameas", "product", "product_exact", "productexact", "product exact",
}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _num(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _derived_metrics(metrics: dict[str, float]) -> dict[str, float | None]:
    impressions = metrics["impressions"]
    clicks = metrics["clicks"]
    orders = metrics["orders"]
    spends = metrics["spends"]
    sales = metrics["sales"]
    return {
        "ctr": clicks / impressions if impressions else None,
        "cpc": spends / clicks if clicks else None,
        "cpa": spends / orders if orders else None,
        "cvr": orders / clicks if clicks else None,
        "acos": spends / sales if sales else None,
    }


def _source_value(item: dict[str, Any], name: str) -> Any:
    value = item.get(name)
    if value not in {None, ""}:
        return value
    source = item.get("source_row")
    return source.get(name) if isinstance(source, dict) else None


def _normalized_object(value: Any) -> str:
    return " ".join(_text(value).split()).casefold()


def _negative_entries(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                yield item
            elif isinstance(item, str):
                yield {"keyword": item}
    elif isinstance(value, dict):
        yield value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            yield {"keyword": value}
        else:
            yield from _negative_entries(parsed)


def _candidate_evidence(rows: Iterable[dict[str, Any]]) -> Iterable[dict[str, Any]]:
    for row in rows:
        evidence = [row]
        for field in ("source_rows", "sources", "source_terms"):
            nested = row.get(field)
            if isinstance(nested, list):
                evidence.extend(item for item in nested if isinstance(item, dict))
        source = row.get("source_row")
        if isinstance(source, dict):
            evidence.append(source)
        for item in evidence:
            yield item
            raw = item.get("raw")
            if isinstance(raw, dict):
                raw_evidence = dict(raw)
                raw_evidence.setdefault("query", item.get("query") or row.get("query"))
                yield raw_evidence


def has_existing_exact_negative(rows: Iterable[dict[str, Any]], action_type: Any, object_value: Any) -> bool:
    """Return true only when current source evidence proves the same exact negative exists."""
    action = _text(action_type)
    if action == "negative_keyword_candidate":
        expected_matches = {"", "negativeexact", "exact", "精准否定", "精确否定"}
    elif action == "asin_negative_candidate":
        expected_matches = {
            "", "negativeproductexact", "product_exact", "productexact", "product exact",
            "asin", "商品精准否定", "商品精确否定", "已否定",
        }
    else:
        return False
    target = _normalized_object(object_value)
    if not target:
        return False
    for source in _candidate_evidence(rows):
        for field in NEGATIVE_FIELDS:
            for entry in _negative_entries(source.get(field)):
                text = entry.get("keyword") or entry.get("keyword_text") or entry.get("asin") or entry.get("text") or entry.get("target_text")
                match = _normalized_object(entry.get("match_type") or entry.get("matchType"))
                level = _normalized_object(entry.get("ng_level") or entry.get("negative_level") or entry.get("level"))
                if text and _normalized_object(text) == target and match in expected_matches and (not level or level == "ad_group"):
                    return True
                if (
                    not text
                    and field == "st_negatives"
                    and level == "ad_group"
                    and _normalized_object(source.get("query")) == target
                    and match in expected_matches
                ):
                    return True
    return False


def compact_evidence(item: dict[str, Any]) -> dict[str, Any]:
    """Keep browser evidence useful without embedding nested MCP/raw payloads."""
    keys = (
        "record_id", "source_record_id", "query", "profile_id", "shop", "sponsored_type",
        "campaign_id", "campaign_name", "ad_group_id", "ad_group_name", "keyword_id",
        "target_id", "targeting_text", "target_match_type", "match_type", "ads_object",
        "campaign_state", "ad_group_state", "target_state", "portfolio_id", "portfolio_name",
        "country", "currency", "start_date", "end_date", "source_page", "relation_type",
        "related_asins", "ad_units", "cpa", "unit_price", "acos", "cpc", "roas", "cvr",
        "ctr", "bid", "default_bid", "st_negatives", "kw_negatives",
        "target_negatives", "product_negatives", *METRIC_FIELDS,
    )
    compact = {}
    raw = item.get("raw") if isinstance(item.get("raw"), dict) else {}
    for key in keys:
        value = item.get(key)
        if (value is None or value == "") and key in NEGATIVE_FIELDS:
            value = raw.get(key)
        if value is not None and value != "":
            compact[key] = value
    return compact


def is_ad_scope_active(item: dict[str, Any]) -> bool:
    """Treat missing legacy state as unknown/usable; reject explicit stopped states."""
    return all(_text(_source_value(item, name)).casefold() in ACTIVE_STATES for name in (
        "campaign_state", "ad_group_state", "target_state"
    ))


def is_listing_active(item: dict[str, Any]) -> bool:
    deleted = _text(item.get("is_delete")).casefold()
    if deleted in TRUE_VALUES:
        return False
    status = _text(item.get("listing_status") or item.get("status")).casefold()
    return not status or status in ACTIVE_LISTING_STATES


def direction_for_action(action_type: Any) -> str:
    value = _text(action_type)
    if value == "negative_keyword_candidate":
        return "negative"
    if value in EXACT_ACTION_TYPES:
        return "exact"
    if value in BID_ACTION_TYPES:
        return "bid"
    if value in {"phrase_negative_candidate", "keep_root_negative_bad_tail"}:
        return "root"
    if value in {"asin_negative_candidate", "asin_negative_observe"}:
        return "asin"
    return "observe"


def logical_action_key(item: dict[str, Any]) -> str:
    if _text(item.get("action_type")) in BID_ACTION_TYPES and _text(item.get("target_id")):
        return "|".join((
            _text(item.get("profile_id")).casefold(),
            _text(item.get("sponsored_type")).casefold(),
            _text(item.get("target_id")).casefold(),
            _text(item.get("action_type")).casefold(),
        ))
    object_value = item.get("root") if item.get("root") else item.get("query")
    parts = (
        item.get("profile_id"), item.get("sponsored_type"), item.get("campaign_id"),
        item.get("ad_group_id"), object_value, item.get("action_type"),
    )
    return "|".join(_text(value).casefold() for value in parts)


def _relation_type(asins: list[str], seen: set[str]) -> str:
    if "shared_group" in seen or len(asins) > 1:
        return "shared_group"
    if asins:
        return "single_product"
    return "unmapped"


def build_action_scopes(candidates: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse raw candidate rows into the exact ad-group action an operator can select."""
    grouped: OrderedDict[str, list[dict[str, Any]]] = OrderedDict()
    for item in candidates:
        if not is_ad_scope_active(item):
            continue
        grouped.setdefault(logical_action_key(item), []).append(item)

    result: list[dict[str, Any]] = []
    for key, rows in grouped.items():
        first = rows[0]
        metrics = {name: sum(_num(_source_value(row, name)) for row in rows) for name in METRIC_FIELDS}
        asins = sorted({_text(asin).upper() for row in rows for asin in row.get("related_asins", []) if _text(asin)})
        relation_types = {_text(row.get("relation_type")) for row in rows}
        action_type = _text(first.get("action_type"))
        object_value = _text(first.get("root") or first.get("query"))
        if action_type == "asin_exact_candidate":
            object_value = canonical_asin(object_value) or object_value.upper()
        source_action_keys = list(dict.fromkeys(_text(row.get("action_key")) for row in rows if _text(row.get("action_key"))))
        source_record_ids = list(dict.fromkeys(
            record_id
            for row in rows
            for record_id in (
                [_text(value) for value in row.get("source_record_ids", []) if _text(value)]
                or ([_text(row.get("source_record_id"))] if _text(row.get("source_record_id")) else [])
            )
        ))
        sources = []
        for row in rows:
            nested_sources = row.get("source_rows")
            if isinstance(nested_sources, list) and nested_sources:
                sources.extend(compact_evidence(source) for source in nested_sources if isinstance(source, dict))
            elif isinstance(row.get("source_row"), dict):
                sources.append(compact_evidence(row["source_row"]))
        already_exact_negative = has_existing_exact_negative(rows, action_type, object_value)
        scope = {
            "scope_key": key,
            "action_key": key,
            "profile_id": _text(first.get("profile_id")),
            "shop": _text(first.get("shop")),
            "sponsored_type": _text(first.get("sponsored_type")).lower(),
            "campaign_id": _text(first.get("campaign_id")),
            "campaign_name": _text(first.get("campaign_name")),
            "ad_group_id": _text(first.get("ad_group_id")),
            "ad_group_name": _text(first.get("ad_group_name")),
            "query": object_value,
            "object": object_value,
            "object_type": "bid_entity" if action_type in BID_ACTION_TYPES else ("asin" if action_type.startswith("asin_") else "search_term"),
            "action_type": action_type,
            "direction": direction_for_action(action_type),
            "already_exact_negative": already_exact_negative,
            "processed_status": "already_exact_negative" if already_exact_negative else "",
            **metrics,
            **_derived_metrics(metrics),
            "reference_cpa": next((row.get("reference_cpa") for row in rows if row.get("reference_cpa") is not None), None),
            "target_match_type": _text(first.get("target_match_type")),
            "related_asins": asins,
            "relation_type": _relation_type(asins, relation_types),
            "source_action_keys": source_action_keys,
            "source_record_ids": source_record_ids,
            "source_count": len(sources) or sum(int(row.get("source_count") or 1) for row in rows),
            "sources": sources,
            "reason_code": _text(first.get("reason_code")),
        }
        if action_type in BID_ACTION_TYPES:
            scope.update({
                "target_id": _text(first.get("target_id")),
                "entity_type": _text(first.get("entity_type")),
                "match_type": _text(first.get("match_type")),
                "current_bid": first.get("current_bid"),
                "suggested_bid": first.get("suggested_bid"),
                "final_bid": first.get("final_bid"),
                "bid_change_rate": first.get("bid_change_rate"),
                "bid_direction": _text(first.get("bid_direction")),
                "bid_status": _text(first.get("bid_status")),
                "bid_reason": _text(first.get("bid_reason")),
                "tool_id": _text(first.get("tool_id")),
                "bid_settings": {
                    "target_id": _text(first.get("target_id")),
                    "current_bid": first.get("current_bid"),
                    "suggested_bid": first.get("suggested_bid"),
                    "final_bid": first.get("final_bid"),
                    "bid_direction": _text(first.get("bid_direction")),
                    "tool_id": _text(first.get("tool_id")),
                },
            })
        result.append(scope)
    return result


def _exact_match_values(item: dict[str, Any]) -> set[str]:
    raw = item.get("raw") if isinstance(item.get("raw"), dict) else {}
    values = {
        _normalized_object(item.get("match_type")),
        _normalized_object(item.get("target_match_type")),
        _normalized_object(raw.get("match_type")),
        _normalized_object(raw.get("target_match_type")),
    }
    return {value.replace("-", "_") for value in values if value}


def _term_exact_object(item: dict[str, Any], *, object_type: str) -> str:
    raw = item.get("raw") if isinstance(item.get("raw"), dict) else {}
    matches = _exact_match_values(item)
    if object_type == "asin":
        if not matches.intersection(PRODUCT_EXACT_MATCHES):
            return ""
        for value in (
            raw.get("target_asin"), raw.get("exp_value"), raw.get("asin"),
            raw.get("target_text"), item.get("targeting_text"), item.get("query"),
        ):
            asin = canonical_asin(value)
            if asin:
                return asin
        return ""
    if not matches.intersection(KEYWORD_EXACT_MATCHES):
        return ""
    return _normalized_object(
        raw.get("keyword_text") or raw.get("targeting_text")
        or item.get("targeting_text") or item.get("query")
    )


def _running_exact_matches(
    scope: dict[str, Any],
    terms: Iterable[dict[str, Any]],
    *,
    promoted_asin: str,
) -> list[dict[str, Any]]:
    if not promoted_asin:
        return []
    object_type = "asin" if scope.get("action_type") == "asin_exact_candidate" else "keyword"
    expected = canonical_asin(scope.get("object") or scope.get("query")) if object_type == "asin" else _normalized_object(scope.get("object") or scope.get("query"))
    result: list[dict[str, Any]] = []
    for term in terms:
        if str(term.get("profile_id") or "") != str(scope.get("profile_id") or ""):
            continue
        if str(term.get("sponsored_type") or "").lower() != str(scope.get("sponsored_type") or "").lower():
            continue
        term_asins = {str(value).upper() for value in term.get("related_asins", []) if _text(value)}
        if promoted_asin not in term_asins or not is_ad_scope_active(term):
            continue
        if _term_exact_object(term, object_type=object_type) != expected:
            continue
        result.append(compact_evidence(term))
    return result


def _running_exact_index(terms: Iterable[dict[str, Any]]) -> dict[tuple[str, str, str, str, str], list[dict[str, Any]]]:
    """Index active exact targets once so large batches do not rescan every row per candidate."""
    result: dict[tuple[str, str, str, str, str], list[dict[str, Any]]] = {}
    for term in terms:
        if not is_ad_scope_active(term):
            continue
        matches = _exact_match_values(term)
        if matches.intersection(PRODUCT_EXACT_MATCHES):
            object_type = "asin"
        elif matches.intersection(KEYWORD_EXACT_MATCHES):
            object_type = "keyword"
        else:
            continue
        object_value = _term_exact_object(term, object_type=object_type)
        if not object_value:
            continue
        compact = compact_evidence(term)
        for promoted_asin in {str(value).upper() for value in term.get("related_asins", []) if _text(value)}:
            key = (
                _text(term.get("profile_id")), _text(term.get("sponsored_type")).lower(),
                promoted_asin, object_type, object_value,
            )
            result.setdefault(key, []).append(compact)
    return result


def enrich_exact_scopes(
    scopes: Iterable[dict[str, Any]],
    terms: Iterable[dict[str, Any]],
    *,
    selected_asin: str = "",
) -> list[dict[str, Any]]:
    """Build one review-only exact plan per product/object and retain source evidence.

    Negative actions intentionally remain ad-group scoped. Exact promotion is different:
    the operator approves one destination for a product/object pair, while every source
    ad group contributes performance evidence to that single plan.
    """
    term_rows = list(terms)
    running_index = _running_exact_index(term_rows)
    selected_product = canonical_asin(selected_asin) or _text(selected_asin).upper()
    passthrough: list[dict[str, Any]] = []
    grouped: OrderedDict[tuple[str, str, str, str, str], list[dict[str, Any]]] = OrderedDict()
    for original in scopes:
        scope = dict(original)
        if scope.get("action_type") not in EXACT_ACTION_TYPES:
            passthrough.append(scope)
            continue
        related_asins = [str(value).upper() for value in scope.get("related_asins", []) if _text(value)]
        promoted_asin = selected_product if selected_product and selected_product in related_asins else (related_asins[0] if len(related_asins) == 1 else "")
        object_type = "asin" if scope.get("action_type") == "asin_exact_candidate" else "keyword"
        expected_object = canonical_asin(scope.get("object") or scope.get("query")) if object_type == "asin" else _normalized_object(scope.get("object") or scope.get("query"))
        key = (
            _text(scope.get("profile_id")), _text(scope.get("sponsored_type")).lower(),
            promoted_asin, object_type, expected_object,
        )
        scope["_exact_promoted_asin"] = promoted_asin
        scope["_exact_object_type"] = object_type
        scope["_exact_expected_object"] = expected_object
        grouped.setdefault(key, []).append(scope)

    result: list[dict[str, Any]] = [*passthrough]
    for key, source_scopes in grouped.items():
        first = source_scopes[0]
        profile_id, sponsored_type, promoted_asin, object_type, expected_object = key
        metrics = {name: sum(_num(scope.get(name)) for scope in source_scopes) for name in METRIC_FIELDS}
        derived = _derived_metrics(metrics)
        historical_cpc = round(float(derived["cpc"]), 2) if derived["cpc"] is not None and derived["cpc"] > 0 else None
        object_value = canonical_asin(first.get("object") or first.get("query")) if object_type == "asin" else " ".join(_text(first.get("object") or first.get("query")).split())

        evidence_scopes: list[dict[str, Any]] = []
        eligible_sources: list[dict[str, Any]] = []
        for source in source_scopes:
            clean_source = {name: value for name, value in source.items() if not name.startswith("_exact_")}
            source_asins = sorted({_text(value).upper() for value in source.get("related_asins", []) if _text(value)})
            eligible = bool(
                sponsored_type == "sp"
                and promoted_asin
                and source.get("relation_type") == "single_product"
                and source_asins == [promoted_asin]
            )
            clean_source["eligible_exact_destination"] = eligible
            clean_source["selected_default_exact_destination"] = False
            evidence_scopes.append(clean_source)
            if eligible:
                eligible_sources.append(clean_source)

        def destination_rank(item: dict[str, Any]) -> tuple[Any, ...]:
            acos = item.get("acos")
            cvr = item.get("cvr")
            return (
                -_num(item.get("orders")),
                float(acos) if acos is not None else float("inf"),
                -(float(cvr) if cvr is not None else -1.0),
                -_num(item.get("clicks")),
                _text(item.get("campaign_id")),
                _text(item.get("ad_group_id")),
            )

        default_source = sorted(eligible_sources, key=destination_rank)[0] if eligible_sources else None
        if default_source is not None:
            for item in evidence_scopes:
                item["selected_default_exact_destination"] = (
                    _text(item.get("campaign_id")) == _text(default_source.get("campaign_id"))
                    and _text(item.get("ad_group_id")) == _text(default_source.get("ad_group_id"))
                )

        matches = running_index.get((
            profile_id, sponsored_type,
            promoted_asin, object_type, expected_object,
        ), []) if promoted_asin and expected_object else []
        blocked_reason = ""
        if sponsored_type != "sp":
            blocked_reason = "unsupported_ad_type"
        elif not promoted_asin:
            blocked_reason = "ambiguous_promoted_asin"
        elif historical_cpc is None:
            blocked_reason = "missing_actual_cpc"

        plan_key = "|".join(("exact-plan", profile_id.casefold(), sponsored_type, promoted_asin.casefold(), object_type, expected_object))
        source_action_keys = list(dict.fromkeys(
            _text(value)
            for scope in source_scopes
            for value in ([scope.get("action_key")] + list(scope.get("source_action_keys") or []))
            if _text(value)
        ))
        source_record_ids = list(dict.fromkeys(
            _text(value)
            for scope in source_scopes
            for value in scope.get("source_record_ids", [])
            if _text(value)
        ))
        flattened_sources = [
            source
            for scope in source_scopes
            for source in (scope.get("sources") or [])
            if isinstance(source, dict)
        ]
        plan_scope = {
            "scope_key": plan_key,
            "action_key": plan_key,
            "profile_id": profile_id,
            "shop": _text(first.get("shop")),
            "sponsored_type": sponsored_type,
            "campaign_id": _text((default_source or {}).get("campaign_id")),
            "campaign_name": _text((default_source or {}).get("campaign_name")),
            "ad_group_id": _text((default_source or {}).get("ad_group_id")),
            "ad_group_name": _text((default_source or {}).get("ad_group_name")),
            "query": object_value or _text(first.get("object") or first.get("query")),
            "object": object_value or _text(first.get("object") or first.get("query")),
            "object_type": "asin" if object_type == "asin" else "search_term",
            "action_type": _text(first.get("action_type")),
            "direction": "exact",
            **metrics,
            **derived,
            "reference_cpa": next((scope.get("reference_cpa") for scope in source_scopes if scope.get("reference_cpa") is not None), None),
            "target_match_type": "/".join(sorted({_text(scope.get("target_match_type")) for scope in source_scopes if _text(scope.get("target_match_type"))})),
            "related_asins": [promoted_asin] if promoted_asin else sorted({_text(value).upper() for scope in source_scopes for value in scope.get("related_asins", []) if _text(value)}),
            "relation_type": "single_product" if promoted_asin else _relation_type(
                sorted({_text(value).upper() for scope in source_scopes for value in scope.get("related_asins", []) if _text(value)}),
                {_text(scope.get("relation_type")) for scope in source_scopes},
            ),
            "source_action_keys": source_action_keys,
            "source_record_ids": source_record_ids,
            "source_count": len(flattened_sources) or sum(int(scope.get("source_count") or 1) for scope in source_scopes),
            "sources": flattened_sources,
            "source_scope_count": len(evidence_scopes),
            "source_scopes": sorted(evidence_scopes, key=lambda item: (_text(item.get("campaign_name")), _text(item.get("ad_group_name")))),
            "reason_code": _text(first.get("reason_code")),
            "already_exact_negative": False,
            "already_exact_running": bool(matches),
            "existing_exact_matches": matches,
            "processed_status": "already_exact_running" if matches else "",
        }
        if matches:
            plan_scope["processed_status"] = "already_exact_running"
        plan_scope["exact_plan"] = {
            "object_type": object_type,
            "object_value": object_value or _text(first.get("object") or first.get("query")),
            "promoted_asin": promoted_asin,
            "source_campaign_id": _text((default_source or {}).get("campaign_id")),
            "source_ad_group_id": _text((default_source or {}).get("ad_group_id")),
            "target_campaign_id": _text((default_source or {}).get("campaign_id")),
            "target_campaign_name": _text((default_source or {}).get("campaign_name")),
            "target_ad_group_id": _text((default_source or {}).get("ad_group_id")),
            "target_ad_group_name": _text((default_source or {}).get("ad_group_name")),
            "historical_cpc": historical_cpc,
            "exact_bid": historical_cpc,
            "bid_source": "historical_cpc",
            "match_type": "PRODUCT_EXACT" if object_type == "asin" else "EXACT",
            "existing_exact_status": "already_exact_running" if matches else "",
            "blocked_reason": blocked_reason,
            "source_scope_count": len(evidence_scopes),
            "target_required": default_source is None and not blocked_reason,
        }
        result.append(plan_scope)
    return result


def _term_contains_root(term: dict[str, Any], root: str) -> bool:
    query = _text(term.get("query"))
    asin = canonical_asin(query)
    if asin:
        return asin == root
    return root in split_words(query)


def build_root_source_rows(
    source_terms: Iterable[dict[str, Any]],
    bad_tail_terms: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Group root evidence by search term so the drawer can show every real source."""
    bad_tail_keys = {
        _normalized_object(item.get("query"))
        for item in bad_tail_terms
        if isinstance(item, dict) and _normalized_object(item.get("query"))
    }
    grouped: OrderedDict[str, list[dict[str, Any]]] = OrderedDict()
    for item in source_terms:
        if not isinstance(item, dict):
            continue
        normalized = _normalized_object(item.get("query"))
        if normalized:
            grouped.setdefault(normalized, []).append(item)

    result: list[dict[str, Any]] = []
    for normalized, rows in grouped.items():
        first = rows[0]
        metrics = {name: sum(_num(row.get(name)) for row in rows) for name in METRIC_FIELDS}
        target_match_types = list(dict.fromkeys(
            _text(row.get("target_match_type") or row.get("match_type"))
            for row in rows
            if _text(row.get("target_match_type") or row.get("match_type"))
        ))
        related_asins = sorted({
            _text(asin).upper()
            for row in rows
            for asin in row.get("related_asins", [])
            if _text(asin)
        })
        result.append({
            "query": _text(first.get("query")),
            "is_bad_tail": normalized in bad_tail_keys,
            **metrics,
            **_derived_metrics(metrics),
            "target_match_types": target_match_types,
            "source_count": len(rows),
            "source_record_ids": list(dict.fromkeys(
                _text(row.get("record_id") or row.get("source_record_id"))
                for row in rows
                if _text(row.get("record_id") or row.get("source_record_id"))
            )),
            "source_rows": [compact_evidence(row) for row in rows],
            "related_asins": related_asins,
        })
    return sorted(result, key=lambda item: (not item["is_bad_tail"], -item["spends"], item["query"].casefold()))


def enrich_root_scopes(roots: Iterable[dict[str, Any]], search_terms: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attach the actionable campaign/ad-group context and exact source terms to roots."""
    contexts: dict[tuple[str, str], dict[str, Any]] = {}
    terms_by_root: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for term in search_terms:
        if not is_ad_scope_active(term):
            continue
        group_key = (_text(term.get("profile_id")), _text(term.get("ad_group_id")))
        contexts.setdefault(group_key, term)
        query = _text(term.get("query"))
        asin = canonical_asin(query)
        roots_in_term = {asin} if asin else set(split_words(query))
        compact = compact_evidence(term)
        for root_name in roots_in_term:
            terms_by_root[(group_key[0], group_key[1], root_name)].append(compact)

    result: list[dict[str, Any]] = []
    for root in roots:
        key = (_text(root.get("profile_id")), _text(root.get("ad_group_id")))
        context = contexts.get(key)
        if context is None:
            continue
        root_name = _text(root.get("root"))
        source_terms = terms_by_root.get((key[0], key[1], root_name), [])
        source_details = build_root_source_rows(source_terms, root.get("bad_tail_terms") or [])
        sponsored_type = _text(context.get("sponsored_type")).lower()
        action_type = _text(root.get("action_type"))
        metrics = {name: _num(root.get(name)) for name in METRIC_FIELDS}
        action_key = "|".join((
            "root", key[0].casefold(), sponsored_type, _text(context.get("campaign_id")).casefold(),
            key[1].casefold(), root_name.casefold(), action_type.casefold(),
        ))
        item = dict(root)
        item.update({
            "action_key": action_key,
            "scope_key": action_key,
            "shop": _text(context.get("shop")),
            "sponsored_type": sponsored_type,
            "portfolio_id": _text(context.get("portfolio_id")),
            "portfolio_name": _text(context.get("portfolio_name")),
            "campaign_id": _text(context.get("campaign_id")),
            "campaign_name": _text(context.get("campaign_name")),
            "ad_group_name": _text(context.get("ad_group_name")),
            "query": root_name,
            "object": root_name,
            "object_type": "root",
            "direction": direction_for_action(action_type),
            **metrics,
            **_derived_metrics(metrics),
            "source_terms": source_terms,
            "source_details": source_details,
            "source_count": len(source_terms),
        })
        result.append(item)
    return result


def _public_root_action(scope: dict[str, Any]) -> dict[str, Any]:
    """Return one selectable/read-only group action without duplicating evidence payloads."""
    hidden = {"source_terms", "source_details", "source_rows", "sources"}
    return {key: value for key, value in scope.items() if key not in hidden}


def build_root_tail_scopes(root_scopes: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Expand keep-root bad tails into independently selectable exact-negative scopes."""
    result: list[dict[str, Any]] = []
    for scope in root_scopes:
        if _text(scope.get("action_type")) != "keep_root_negative_bad_tail":
            continue
        for term in scope.get("source_details") or []:
            if not isinstance(term, dict) or not term.get("is_bad_tail"):
                continue
            query = _text(term.get("query"))
            normalized = _normalized_object(query)
            if not normalized:
                continue
            source_rows = [row for row in term.get("source_rows") or [] if isinstance(row, dict)]
            already_exact_negative = has_existing_exact_negative(
                source_rows, "negative_keyword_candidate", query,
            )
            metrics = {name: _num(term.get(name)) for name in METRIC_FIELDS}
            action_key = f"{_text(scope.get('action_key'))}|tail|{normalized}"
            related_asins = sorted({
                _text(asin).upper()
                for asin in (term.get("related_asins") or scope.get("related_asins") or [])
                if _text(asin)
            })
            result.append({
                "scope_key": action_key,
                "action_key": action_key,
                "parent_action_key": _text(scope.get("action_key")),
                "profile_id": _text(scope.get("profile_id")),
                "shop": _text(scope.get("shop")),
                "sponsored_type": _text(scope.get("sponsored_type")).lower(),
                "portfolio_id": _text(scope.get("portfolio_id")),
                "portfolio_name": _text(scope.get("portfolio_name")),
                "campaign_id": _text(scope.get("campaign_id")),
                "campaign_name": _text(scope.get("campaign_name")),
                "ad_group_id": _text(scope.get("ad_group_id")),
                "ad_group_name": _text(scope.get("ad_group_name")),
                "root": _text(scope.get("root") or scope.get("query")),
                "query": query,
                "object": query,
                "object_type": "search_term",
                "action_type": "negative_keyword_candidate",
                "direction": "negative",
                "target_match_type": "negativeExact",
                "target_match_types": list(term.get("target_match_types") or []),
                "already_exact_negative": already_exact_negative,
                "processed_status": "already_exact_negative" if already_exact_negative else "",
                **metrics,
                **_derived_metrics(metrics),
                "reference_cpa": scope.get("reference_cpa"),
                "related_asins": related_asins,
                "relation_type": _text(scope.get("relation_type")),
                "source_record_ids": list(term.get("source_record_ids") or []),
                "source_count": int(term.get("source_count") or len(source_rows)),
                "sources": source_rows,
                "reason_code": "root_bad_tail",
            })
    return result


def build_root_trace_summaries(root_scopes: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Roll group-level root findings into one browser row per store and normalized root."""
    grouped: OrderedDict[tuple[str, str], list[dict[str, Any]]] = OrderedDict()
    for scope in root_scopes:
        root = _normalized_object(scope.get("root") or scope.get("query"))
        profile_id = _text(scope.get("profile_id"))
        if profile_id and root:
            grouped.setdefault((profile_id, root), []).append(scope)

    result: list[dict[str, Any]] = []
    for (profile_id, _), scopes in grouped.items():
        first = scopes[0]
        metrics = {name: sum(_num(scope.get(name)) for scope in scopes) for name in METRIC_FIELDS}
        asins = sorted({
            _text(asin).upper()
            for scope in scopes
            for asin in scope.get("related_asins", [])
            if _text(asin)
        })
        relation_types = {_text(scope.get("relation_type")) for scope in scopes}
        sponsored_types = sorted({
            _text(scope.get("sponsored_type")).lower()
            for scope in scopes
            if _text(scope.get("sponsored_type"))
        })
        search_terms = {
            _normalized_object(term.get("query"))
            for scope in scopes
            for term in scope.get("source_details") or []
            if isinstance(term, dict) and _normalized_object(term.get("query"))
        }
        action_counts: dict[str, int] = {}
        for scope in scopes:
            action_type = _text(scope.get("action_type"))
            action_counts[action_type] = action_counts.get(action_type, 0) + 1
        root_name = _text(first.get("root") or first.get("query"))
        result.append({
            "summary_key": f"root-summary|{profile_id.casefold()}|{_normalized_object(root_name)}",
            "profile_id": profile_id,
            "shop": _text(first.get("shop")),
            "root": root_name,
            "query": root_name,
            "object": root_name,
            "object_type": "root",
            "sponsored_type": sponsored_types[0] if len(sponsored_types) == 1 else "mixed",
            "sponsored_types": sponsored_types,
            "group_count": len({
                (
                    _text(scope.get("sponsored_type")).lower(),
                    _text(scope.get("campaign_id")),
                    _text(scope.get("ad_group_id")),
                )
                for scope in scopes
            }),
            "search_term_count": len(search_terms),
            "source_count": sum(int(scope.get("source_count") or 0) for scope in scopes),
            "bad_tail_count": sum(
                1
                for scope in scopes
                for term in scope.get("source_details") or []
                if isinstance(term, dict) and term.get("is_bad_tail")
            ),
            "action_counts": action_counts,
            **metrics,
            **_derived_metrics(metrics),
            "related_asins": asins,
            "relation_type": _relation_type(asins, relation_types),
        })
    return sorted(result, key=lambda item: (item["spends"], item["clicks"], item["root"].casefold()), reverse=True)


def build_root_detail(root_scopes: Iterable[dict[str, Any]], root: str) -> dict[str, Any]:
    """Build the root -> unique ad group -> unique search term review hierarchy."""
    normalized_root = _normalized_object(root)
    scopes = [
        scope for scope in root_scopes
        if _normalized_object(scope.get("root") or scope.get("query")) == normalized_root
    ]
    if not scopes:
        return {
            "root": _text(root), "groups": [], "group_count": 0,
            "search_term_count": 0, "source_count": 0,
            **{name: 0.0 for name in METRIC_FIELDS},
            **_derived_metrics({name: 0.0 for name in METRIC_FIELDS}),
        }

    tail_by_parent: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for tail in build_root_tail_scopes(scopes):
        tail_by_parent[_text(tail.get("parent_action_key"))][_normalized_object(tail.get("query"))] = tail

    groups: list[dict[str, Any]] = []
    unique_terms: set[str] = set()
    for scope in scopes:
        parent_key = _text(scope.get("action_key"))
        search_terms = []
        for term in scope.get("source_details") or []:
            if not isinstance(term, dict):
                continue
            row = {key: value for key, value in term.items() if key != "source_rows"}
            normalized_query = _normalized_object(term.get("query"))
            if normalized_query:
                unique_terms.add(normalized_query)
            action = tail_by_parent.get(parent_key, {}).get(normalized_query)
            row["action"] = action
            search_terms.append(row)
        action_type = _text(scope.get("action_type"))
        group_action = _public_root_action(scope) if action_type == "phrase_negative_candidate" else None
        metrics = {name: _num(scope.get(name)) for name in METRIC_FIELDS}
        groups.append({
            "group_key": parent_key,
            "profile_id": _text(scope.get("profile_id")),
            "shop": _text(scope.get("shop")),
            "sponsored_type": _text(scope.get("sponsored_type")).lower(),
            "portfolio_id": _text(scope.get("portfolio_id")),
            "portfolio_name": _text(scope.get("portfolio_name")),
            "campaign_id": _text(scope.get("campaign_id")),
            "campaign_name": _text(scope.get("campaign_name")),
            "ad_group_id": _text(scope.get("ad_group_id")),
            "ad_group_name": _text(scope.get("ad_group_name")),
            "root": _text(scope.get("root") or scope.get("query")),
            "action_type": action_type,
            "action": group_action,
            "bad_tail_count": sum(bool(term.get("is_bad_tail")) for term in search_terms),
            "search_term_count": len(search_terms),
            "source_count": int(scope.get("source_count") or 0),
            **metrics,
            **_derived_metrics(metrics),
            "related_asins": list(scope.get("related_asins") or []),
            "relation_type": _text(scope.get("relation_type")),
            "search_terms": search_terms,
        })

    priority = {"phrase_negative_candidate": 0, "keep_root_negative_bad_tail": 1, "root_observe": 2}
    groups.sort(key=lambda item: (priority.get(item["action_type"], 3), -item["spends"], item["ad_group_name"].casefold()))
    metrics = {name: sum(_num(group.get(name)) for group in groups) for name in METRIC_FIELDS}
    first = scopes[0]
    asins = sorted({
        _text(asin).upper()
        for scope in scopes
        for asin in scope.get("related_asins", [])
        if _text(asin)
    })
    relation_types = {_text(scope.get("relation_type")) for scope in scopes}
    return {
        "profile_id": _text(first.get("profile_id")),
        "shop": _text(first.get("shop")),
        "root": _text(first.get("root") or root),
        "group_count": len(groups),
        "search_term_count": len(unique_terms),
        "source_count": sum(int(group.get("source_count") or 0) for group in groups),
        **metrics,
        **_derived_metrics(metrics),
        "related_asins": asins,
        "relation_type": _relation_type(asins, relation_types),
        "groups": groups,
    }


def build_recommendations(scopes: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Roll executable scopes up by visible object while retaining every child scope."""
    grouped: OrderedDict[tuple[str, str, str, str, str, str], list[dict[str, Any]]] = OrderedDict()
    for scope in scopes:
        object_value = _text(scope.get("object") or scope.get("query") or scope.get("root"))
        promoted_asin = _text((scope.get("exact_plan") or {}).get("promoted_asin")).upper() if scope.get("direction") == "exact" else ""
        entity_identity = _text(scope.get("target_id")) if scope.get("direction") == "bid" else promoted_asin
        key = (
            _text(scope.get("profile_id")), _text(scope.get("sponsored_type")).lower(),
            _text(scope.get("direction")), _text(scope.get("object_type")), object_value.casefold(), entity_identity,
        )
        grouped.setdefault(key, []).append(scope)

    recommendations: list[dict[str, Any]] = []
    for key, child_scopes in grouped.items():
        first = child_scopes[0]
        metrics = {name: sum(_num(scope.get(name)) for scope in child_scopes) for name in METRIC_FIELDS}
        asins = sorted({_text(asin).upper() for scope in child_scopes for asin in scope.get("related_asins", []) if _text(asin)})
        relation_types = {_text(scope.get("relation_type")) for scope in child_scopes}
        direction = key[2]
        priority = metrics["sales"] if direction == "exact" else metrics["spends"]
        object_value = _text(first.get("object") or first.get("query") or first.get("root"))
        processed_flags = [
            bool(scope.get("already_exact_negative") or scope.get("already_exact_running"))
            for scope in child_scopes
        ]
        recommendations.append({
            "recommendation_key": "|".join(key),
            "profile_id": key[0],
            "shop": _text(first.get("shop")),
            "sponsored_type": key[1],
            "direction": direction,
            "object_type": key[3],
            "object": object_value,
            **metrics,
            **_derived_metrics(metrics),
            "priority": priority,
            "scope_count": len(child_scopes),
            "pending_scope_count": sum(not flag for flag in processed_flags),
            "processed_scope_count": sum(processed_flags),
            "already_exact_negative": all(bool(scope.get("already_exact_negative")) for scope in child_scopes),
            "already_exact_running": all(bool(scope.get("already_exact_running")) for scope in child_scopes),
            "related_asins": asins,
            "relation_type": _relation_type(asins, relation_types),
            "scopes": sorted(child_scopes, key=lambda item: _num(item.get("spends")), reverse=True),
        })
    return sorted(recommendations, key=lambda item: (item["priority"], item["spends"], item["clicks"]), reverse=True)


def group_trace_rows(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Show one trace row per campaign/ad-group/search-term while retaining target evidence."""
    grouped: OrderedDict[tuple[str, str, str, str, str], list[dict[str, Any]]] = OrderedDict()
    for row in rows:
        key = (
            _text(row.get("profile_id")), _text(row.get("sponsored_type")).lower(),
            _text(row.get("campaign_id")), _text(row.get("ad_group_id")),
            _text(row.get("query")).casefold(),
        )
        grouped.setdefault(key, []).append(row)

    result: list[dict[str, Any]] = []
    for source_rows in grouped.values():
        first = source_rows[0]
        item = {key: value for key, value in first.items() if key not in {"actions", "source_rows"}}
        metrics = {name: sum(_num(row.get(name)) for row in source_rows) for name in METRIC_FIELDS}
        actions = []
        seen_actions = set()
        for row in source_rows:
            for action in row.get("actions", []):
                action_key = _text(action.get("action_key"))
                if action_key and action_key not in seen_actions:
                    seen_actions.add(action_key)
                    actions.append(action)
        asins = sorted({_text(asin).upper() for row in source_rows for asin in row.get("related_asins", []) if _text(asin)})
        relation_types = {_text(row.get("relation_type")) for row in source_rows}
        evidence = [{key: value for key, value in row.items() if key not in {"actions", "source_rows"}} for row in source_rows]
        item.update({
            **metrics,
            **_derived_metrics(metrics),
            "related_asins": asins,
            "relation_type": _relation_type(asins, relation_types),
            "source_count": len(source_rows),
            "source_record_ids": list(dict.fromkeys(_text(row.get("record_id")) for row in source_rows if _text(row.get("record_id")))),
            "source_rows": evidence if len(evidence) > 1 else [],
            "actions": actions,
        })
        result.append(item)
    return result
