"""Create one fresh, immutable B-line source batch; never import A-line runtime data."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from b_ops.collect.ledger import save_source_response
from b_ops.collect.ads_targets import (collect_targets_by_profile, target_evidence_by_product,
                                       collect_campaign_settings, enrich_targets_with_campaigns)
from b_ops.collect.lingxing import LingxingClient, LingxingError, collect_pages, extract_data
from b_ops.collect.sif import SifClient
from b_ops.collect.sif_discovery import collect_competitor_pool, choose_competitor_seed
from b_ops.collect.sif_queue import SifRunBudget, build_sif_queue, keyword_batches
from b_ops.collect.sif_ranks import collect_rank_history, current_rank_fields, recent_rank_windows
from b_ops.diagnose.ads import diagnose_search_terms, specialist_fingerprint
from b_ops.diagnose.ads_decisions import (group_scoped_actions, reconcile_exact_targets,
                                         target_bid_reviews, summarize_rank_evidence)
from b_ops.diagnose.inventory import inventory_issues
from b_ops.diagnose.keyword_evidence import build_keyword_evidence
from b_ops.diagnose.listing import listing_issues
from b_ops.diagnose.prioritize import prioritize
from b_ops.model.identity import map_profiles
from b_ops.model.metrics import iso_weeks
from b_ops.model.sales_pace import sales_pace
from b_ops.model.snapshot import normalize_products, number
from b_ops.model.storage import StateStore, normalize_keyword


def _write_json(path: Path, value) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n").encode("utf-8")
    path.write_bytes(encoded)
    return hashlib.sha256(encoded).hexdigest()


def _state_digest(path: Path) -> str | None:
    """Detect local review/wordbook edits made while an immutable run is collecting."""
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def _find_total(value):
    if isinstance(value, dict):
        for name in ("recordsFiltered", "total", "count"):
            if name in value and isinstance(value[name], (int, float)):
                return int(value[name])
        for item in value.values():
            found = _find_total(item)
            if found is not None:
                return found
    return None


class RecordedLingxing:
    def __init__(self, client: LingxingClient, run_dir: Path, run_id: str, ledger: list):
        self.client, self.run_dir, self.run_id, self.ledger = client, run_dir, run_id, ledger

    def read(self, tool: str, params: dict):
        response = self.client.read(tool, params)
        record = save_source_response(self.run_dir, self.run_id, "lingxing", tool, params, response)
        if getattr(self.client, "source_run_id", None):
            record["replayed_from_b_run"] = self.client.source_run_id
        self.ledger.append(record)
        return response


class RecordedSif:
    def __init__(self, client: SifClient, run_dir: Path, run_id: str, ledger: list):
        self.client, self.run_dir, self.run_id, self.ledger = client, run_dir, run_id, ledger

    def call(self, tool: str, params: dict):
        response = self.client.call(tool, params)
        record = save_source_response(self.run_dir, self.run_id, "sif", tool, params, response)
        if getattr(self.client, "source_run_id", None) and getattr(self.client, "last_call_source", "replay") == "replay":
            record["replayed_from_b_run"] = self.client.source_run_id
        self.ledger.append(record)
        return response


def _search_terms(client, profile: str, start: str, end: str) -> tuple[list[dict], dict]:
    rows, seen = [], set()
    total = None
    for page in range(1, 201):
        response = client.read("ad_campaign_search_term_report", {
            "report_date": f"{start} - {end}", "profile_ids": [profile], "page": page,
            "length": 500, "sort_field": "spends", "sort_type": "desc", "with_ring": False,
        })
        part = extract_data(response)
        if isinstance(part, dict):
            part = part.get("data") or part.get("list") or []
        if not isinstance(part, list):
            raise LingxingError("search term page shape mismatch")
        found_total = _find_total(response)
        if found_total is not None:
            if total is not None and total != found_total:
                raise LingxingError("search term total changed")
            total = found_total
        detail = [item for item in part if isinstance(item, dict) and str(item.get("query") or "").strip()]
        for item in detail:
            identity = (str(item.get("record_id") or ""), str(item.get("campaign_id") or ""),
                        str(item.get("ad_group_id") or ""), str(item.get("query") or ""),
                        str(item.get("keyword_id") or item.get("target_id") or ""))
            if identity in seen:
                raise LingxingError("duplicate search term page row")
            seen.add(identity)
            rows.append({**item, "profile_id": profile, "_source_page": page})
        if (total is not None and len(rows) >= total) or len(part) < 500:
            break
    else:
        raise LingxingError("search term pagination bound exceeded")
    if total is not None and len(rows) != total:
        raise LingxingError(f"search term page incomplete {len(rows)}/{total}")
    return rows, {"rows": len(rows), "reported_total": total}


def _group_links(client, products: dict, profile_to_sid: dict, start: str, end: str) -> tuple[dict, dict]:
    links: dict[tuple[str, str], set[str]] = {}
    attempts = 0
    failures = 0
    for profile, sid in profile_to_sid.items():
        for product in products.values():
            if product["sid"] != sid or not product["skus"]:
                continue
            attempts += 1
            try:
                response = client.read("ad_campaign_group_report", {
                    "report_date": f"{start} - {end}", "profile_ids": [profile], "with_ring": 0,
                    "sku": list(product["skus"]), "page": 1, "length": 1000,
                    "sort_field": "spends", "sort_type": "desc",
                })
                data = extract_data(response)
                rows = data if isinstance(data, list) else (data.get("data") or data.get("list") or [])
                if not isinstance(rows, list):
                    raise ValueError("group report shape")
                for row in rows:
                    group = str(row.get("ad_group_id") or row.get("adGroupId") or "")
                    if group:
                        links.setdefault((profile, group), set()).add(product["asin"])
            except Exception:
                failures += 1
    return links, {"requests": attempts, "failed": failures, "linked_groups": len(links)}


def _normalize_search(rows: list[dict], links: dict) -> list[dict]:
    result = []
    for row in rows:
        profile = str(row.get("profile_id") or "")
        group = str(row.get("ad_group_id") or "")
        result.append({
            "profile_id": profile, "sponsored_type": str(row.get("sponsored_type") or row.get("ad_sponsored_type") or "").lower(),
            "campaign_id": str(row.get("campaign_id") or ""), "campaign_name": str(row.get("campaign_name") or ""),
            "ad_group_id": group, "ad_group_name": str(row.get("ad_group_name") or ""),
            "query": str(row.get("query") or ""),
            "target_match_type": str(row.get("target_match_type") or row.get("match_type") or ""),
            "match_type": str(row.get("match_type") or ""),
            "targeting_text": str(row.get("targeting_text") or ""),
            "campaign_state": str(row.get("campaign_state") or ""),
            "ad_group_state": str(row.get("ad_group_state") or ""),
            "target_state": str(row.get("target_state") or ""),
            "impressions": number(row.get("impressions")),
            "clicks": number(row.get("clicks")), "spends": number(row.get("spends")),
            "orders": number(row.get("orders")), "sales": number(row.get("sales")),
            "bid": number(row.get("bid")) or number(row.get("default_bid")),
            "record_id": str(row.get("record_id") or row.get("keyword_id") or row.get("target_id") or ""),
            "related_asins": sorted(links.get((profile, group), set())),
            "relation_type": "shared_group" if len(links.get((profile, group), set())) > 1 else "single_product" if links.get((profile, group)) else "unmapped",
            "st_negatives": row.get("st_negatives") or [],
            "raw": {key: row.get(key) for key in ("target_asin", "exp_value", "asin", "target_text",
                                                  "keyword_text", "targeting_text", "target_match_type",
                                                  "match_type", "st_negatives") if row.get(key) is not None},
        })
    return result


def _sif_terms(value) -> list[dict]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if not isinstance(value, dict):
        return []
    for name in ("top_keywords", "keywords", "list", "data", "rows"):
        if isinstance(value.get(name), list):
            return [item for item in value[name] if isinstance(item, dict)]
    return []


def signal_market_fields(row: dict) -> dict:
    """Keep SIF's already-returned estimates separate from Lingxing actuals."""
    fields = {}
    for source, target in (("traffic_share", "sif_traffic_share"),
                           ("natural_ratio", "sif_natural_ratio"),
                           ("top3_click_share", "sif_top3_click_share"),
                           ("top3_conversion_share", "sif_top3_conversion_share")):
        value = number(row.get(source))
        fields[target] = value if value is not None and 0 <= value <= 1 else None
    value = number(row.get("cpc_median"))
    fields["sif_cpc_median"] = value if value is not None and value >= 0 else None
    return fields


def _refresh(root: Path, lingxing: LingxingClient, sif: SifClient | None,
            *, today: date | None = None, sif_product_limit: int = 25,
            competitor_focus_asins: set[str] | None = None) -> dict:
    today = today or date.today()
    rank_windows = recent_rank_windows(today)
    rank_window = [rank_windows[0][0], rank_windows[-1][1]]
    run_id = "b-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-") + uuid4().hex[:6]
    run_dir = root / "storage" / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    ledger = []
    lx = RecordedLingxing(lingxing, run_dir, run_id, ledger)
    sf = RecordedSif(sif, run_dir, run_id, ledger) if sif else None
    status = {}
    weeks = iso_weeks(today, count=8)
    try:
        shops = extract_data(lx.read("get_multi_platform_shop_list", {"platform_code": [10001]}))
        if not isinstance(shops, list) or not shops:
            raise ValueError("shop list empty")
        sids = [str(row.get("s_id")) for row in shops if row.get("s_id")]
        listings = collect_pages(lx, "erp_listing", {"pvi_ids": "", "sids": ",".join(sids)},
                                 rows_key="list", total_key="total", size=500)
        status["catalog"] = {"state": "verified", "shops": len(shops), "listing_rows": len(listings)}
        if getattr(lingxing, "source_run_id", None):
            status["lingxing_transport"] = {"state": "same_day_b_raw_replay", "source_run_id": lingxing.source_run_id}
        if sif and getattr(sif, "source_run_id", None):
            status["sif_transport"] = {"state": getattr(sif, "transport_state", "historical_b_raw_replay"),
                                       "source_run_id": sif.source_run_id}
        try:
            stock = collect_pages(lx, "get_fba_stock_list", {"sid": ",".join(sids), "is_hide_zero_stock": "0"},
                                  rows_key="list", total_key="total", size=500)
            status["fba_stock"] = {"state": "verified", "rows": len(stock)}
        except Exception as exc:
            stock = []
            status["fba_stock"] = {"state": "unavailable", "error_type": type(exc).__name__}
        performance = []
        for shop in shops:
            sid = str(shop["s_id"])
            for week in weeks:
                params = {"sids": sid, "start_date": week["start"], "end_date": week["end"],
                          "date_type": "purchase", "date_view_type": "week", "date_view_order_type": 1,
                          "summary_field": "asin", "turn_on_summary": 1, "currency_code": str(shop.get("currency") or "")}
                part = collect_pages(lx, "query_product_performance_asin_lists", params,
                                     rows_key="list", total_key="total", size=500)
                performance.extend({**row, "_requested_sid": sid, "_week_start": week["start"]} for row in part)
        status["performance"] = {"state": "verified", "rows": len(performance), "weeks": len(weeks)}
        products, gaps = normalize_products({"shops": shops, "listings": listings, "stock": stock,
                                              "performance": performance}, weeks)
        for product in products.values():
            product["sales_pace"] = sales_pace(product)
        auth = extract_data(lx.read("ad_auth_shops", {"page": 1, "length": 1000}))
        profiles = map_profiles(auth if isinstance(auth, list) else [])
        status["ad_auth"] = {"state": "verified", "profiles": len(profiles)}
        end = (today - timedelta(days=1)).isoformat()
        start = (today - timedelta(days=60)).isoformat()
        search_rows = []
        for profile in profiles:
            try:
                part, detail = _search_terms(lx, profile, start, end)
                search_rows.extend(part)
                status[f"search_terms:{profile}"] = {"state": "verified", **detail}
            except Exception as exc:
                status[f"search_terms:{profile}"] = {"state": "unavailable", "error_type": type(exc).__name__}
        links, links_status = _group_links(lx, products, profiles, start, end)
        status["group_links"] = {"state": "partial" if links_status["failed"] else "verified", **links_status}
        normalized_search = _normalize_search(search_rows, links)
        internal_evidence = build_keyword_evidence(normalized_search, profiles, products)
        target_rows, target_status = collect_targets_by_profile(lx, profiles, rank_window[0], rank_window[1])
        for profile, detail in target_status.items():
            status[f"keyword_targets:{profile}"] = detail
        campaign_settings = []
        for profile in profiles:
            try:
                rows, detail = collect_campaign_settings(lx, profile, rank_window[0], rank_window[1])
                campaign_settings.extend(rows)
                status[f"campaign_settings:{profile}"] = detail
            except Exception as exc:
                status[f"campaign_settings:{profile}"] = {"state": "unavailable", "error_type": type(exc).__name__}
        target_rows = enrich_targets_with_campaigns(target_rows, campaign_settings)
        target_evidence = target_evidence_by_product(target_rows, links, profiles, products)
        ads_source_complete = bool(profiles) and all(
            status.get(f"search_terms:{profile}", {}).get("state") == "verified" for profile in profiles
        ) and links_status["failed"] == 0
        all_actions = reconcile_exact_targets(group_scoped_actions(
            diagnose_search_terms(normalized_search, source_complete=ads_source_complete), products, profiles),
            target_rows, links, products, profiles, target_status=target_status)
        actions = [action for action in all_actions if action["kind"] != "observe" or action["clicks"] >= 10 or action["orders"] >= 2]
        status["ads_diagnosis"] = {"evaluated": len(all_actions), "retained": len(actions),
                                   "executable": sum(action["executable"] for action in actions),
                                   "reviewable": sum(action["reviewable"] for action in actions),
                                   "processed": sum(bool(action["processed_status"]) for action in actions),
                                   "exact_plans": sum(action["kind"] == "exact" for action in actions),
                                   "source_complete": ads_source_complete,
                                   "specialist_sha256": specialist_fingerprint()}
        state_path = root / "storage" / "state" / "ops_state.sqlite3"
        staged_state_path = run_dir / "state_work.sqlite3"
        source_state_digest = _state_digest(state_path)
        if state_path.exists():
            shutil.copy2(state_path, staged_state_path)
        state = StateStore(staged_state_path)
        applied_tracking = state.apply_pending_tracking(run_id)
        status["operator_tracking"] = applied_tracking
        keyword_snapshot = {}
        demand_by_product = {}
        signals_by_product = {}
        for product in products.values():
            keyword_snapshot[product["key"]] = {"terms": [], "sif_state": "not_queried"}
        product_index = {(p["sid"], p["asin"]): p for p in products.values()}
        selected_terms: dict[str, list[dict]] = {}
        for action in actions:
            if not action["query"] or len(action["query"]) > 120:
                continue
            sid = profiles.get(action["profile_id"])
            for asin in action["affected_asins"]:
                product = product_index.get((sid, asin))
                if product:
                    selected_terms.setdefault(product["key"], []).append(action)
        keyword_additions = []
        for key, candidates in selected_terms.items():
            product = products[key]
            top = sorted(candidates, key=lambda item: (item["orders"] * 10 + item["clicks"], item["spend"]), reverse=True)
            for action in top[:25]:
                keyword_additions.append({"site": product["site"], "asin": product["asin"],
                                          "keyword": action["query"], "source": "lingxing_search_term",
                                          "reason": "内部广告搜索词达到复核门槛", "run_id": run_id, "sid": product["sid"]})
        for key, words in target_evidence.items():
            product = products[key]
            for matched in words.values():
                for target in matched:
                    if target["match_type"] == "exact" and 0 < len(target["keyword"]) <= 120:
                        keyword_additions.append({"site": product["site"], "asin": product["asin"],
                                                  "keyword": target["keyword"], "source": "lingxing_exact_target",
                                                  "reason": "领星 SP 精准关键词目标报表", "run_id": run_id,
                                                  "sid": product["sid"]})
        state.add_keywords(keyword_additions)
        if sf:
            last_success = state.sif_last_success_map()
            queue = build_sif_queue(list(products.values()), limit=sif_product_limit,
                                    last_success=last_success,
                                    manual_priority=state.sif_priority_keys() |
                                    state.competitor_priority_keys(list(products.values())))
            for key, reason in queue["deferred"].items():
                keyword_snapshot[key]["sif_state"] = "not_queued"
                keyword_snapshot[key]["sif_queue_reason"] = reason
            sif_budget = SifRunBudget(rank_limit=min(max(sif_product_limit, 0), 25))
            competitor_parents_seen = set()
            competitor_parent_limit = 3
            for entry in queue["selected"]:
                product = entry["products"][0]
                members = entry["products"]
                key = product["key"]
                for member in members:
                    keyword_snapshot[member["key"]]["sif_queue_reason"] = entry["reason"]
                    keyword_snapshot[member["key"]]["sif_lane"] = entry["lane"]
                if not sif_budget.can_query_signal():
                    for member in members:
                        keyword_snapshot[member["key"]]["sif_state"] = "deferred_after_repeated_failures"
                    continue
                try:
                    value = sf.call("market_get_asin_keyword_signals", {
                        "asin": product["asin"], "country": product["site"],
                        "time_type": "lately", "time_value": "7", "topN": 50})
                    rows = _sif_terms(value)
                    for member in members:
                        keyword_snapshot[member["key"]]["sif_state"] = "verified" if rows else "no_rows"
                    state.record_sif_fetch(product["site"], product["asin"], run_id, keyword_snapshot[key]["sif_state"])
                    sif_budget.record_signal_success()
                    sif_additions = []
                    signal_rows = []
                    signals_by_product[key] = {}
                    for row in rows[:50]:
                        term = str(row.get("keyword") or row.get("word") or "").strip()
                        if term:
                            signals_by_product[key][normalize_keyword(term)] = {
                                **current_rank_fields(row),
                                "rank_observed_at": row.get("organic_rank_time_us") or row.get("sp_rank_time_us"),
                                **signal_market_fields(row),
                            }
                        if term and len(sif_additions) < 30:
                            sif_additions.append({"site": product["site"], "asin": product["asin"],
                                                  "keyword": term, "source": "sif_asin_signals",
                                                  "reason": "SIF ASIN 关键词信号", "run_id": run_id, "sid": product["sid"]})
                            signal_rows.append(row)
                    added_ids = state.add_keywords(sif_additions)
                    for keyword_id in added_ids:
                        state.mark_sif_core(keyword_id, product["sid"], run_id)
                    for member in members[1:]:
                        state.add_keywords([{**row, "sid": member["sid"]} for row in sif_additions])
                        for keyword_id in added_ids:
                            state.mark_sif_core(keyword_id, member["sid"], run_id)
                        signals_by_product[member["key"]] = signals_by_product[key]
                    for row, keyword_id in zip(signal_rows, added_ids):
                        rank = number(row.get("organic_rank"))
                        timestamp = str(row.get("organic_rank_time_us") or "")
                        if rank is not None and rank > 0 and len(timestamp) >= 10:
                            state.record_rank(keyword_id, timestamp[:10], "natural", rank, "absolute_rank", run_id)
                        elif row.get("organic_rank") and len(timestamp) >= 10:
                            state.record_rank(keyword_id, timestamp[:10], "natural", None,
                                              "reported_position", run_id, display=str(row["organic_rank"]))
                        ad_position = str(row.get("sp_rank") or "").strip()
                        ad_timestamp = str(row.get("sp_rank_time_us") or "")
                        if ad_position and len(ad_timestamp) >= 10:
                            state.record_rank(keyword_id, ad_timestamp[:10], "advertising", None,
                                              "reported_position", run_id, display=ad_position)
                    parent_asin = str(product.get("parent_asin") or product["asin"]).upper()
                    parent_key = (product["sid"], product["site"], parent_asin)
                    focused = competitor_focus_asins is None or product["asin"] in competitor_focus_asins
                    if focused and parent_key not in competitor_parents_seen and len(competitor_parents_seen) < competitor_parent_limit:
                        competitor_parents_seen.add(parent_key)
                        seed = choose_competitor_seed(rows, product.get("english_title") or "")
                        saved_competitors = state.list_competitors(product["sid"], product["site"], parent_asin)
                        if seed or any(row["active"] for row in saved_competitors):
                            try:
                                own_words = {str(row.get("keyword") or row.get("word") or "") for row in rows}
                                own_words.update(internal_evidence.get(key, {}).keys())
                                pool = collect_competitor_pool(sf, state, sid=product["sid"], site=product["site"],
                                                               parent_asin=parent_asin, asin=product["asin"],
                                                               seed=seed, run_id=run_id, own_terms=own_words,
                                                               target_title=product.get("english_title") or "",
                                                               target_price=number(product.get("price")))
                                keyword_snapshot[key]["competitor_discovery"] = pool
                                for member in members[1:]:
                                    keyword_snapshot[member["key"]]["competitor_discovery"] = pool
                                    state.add_keywords([{"site": member["site"], "asin": member["asin"],
                                                        "keyword": word, "source": "sif_competitor_gap",
                                                        "reason": f"父体 {parent_asin} 竞品机会候选；待内部核对",
                                                        "run_id": run_id, "sid": member["sid"]}
                                                       for word in pool["candidate_keywords"]])
                            except Exception as exc:
                                failure = "replay_missing" if type(exc).__name__ == "ReplayMissing" else "source_failed"
                                for member in members:
                                    keyword_snapshot[member["key"]]["competitor_discovery"] = {
                                        "state": failure, "error_type": type(exc).__name__, "seed": seed}
                        else:
                            for member in members:
                                keyword_snapshot[member["key"]]["competitor_discovery"] = {"state": "no_seed"}
                except Exception as exc:
                    failure_state = sif_budget.record_signal_error(exc)
                    for member in members:
                        keyword_snapshot[member["key"]]["sif_state"] = failure_state
                        keyword_snapshot[member["key"]]["sif_error_type"] = type(exc).__name__
                        keyword_snapshot[member["key"]]["sif_http_status"] = getattr(exc, "status_code", None)
                        keyword_snapshot[member["key"]]["sif_rpc_code"] = getattr(exc, "rpc_code", None)
                        keyword_snapshot[member["key"]]["sif_error_kind"] = getattr(exc, "kind", None)
                        keyword_snapshot[member["key"]]["sif_error_hint"] = getattr(exc, "error_hint", None)
                        keyword_snapshot[member["key"]]["sif_error_fingerprint"] = getattr(exc, "error_fingerprint", None)
                    if failure_state == "source_failed":
                        state.record_sif_fetch(product["site"], product["asin"], run_id, failure_state)
                    continue
                if sif_budget.reserve_rank():
                    core = [row for row in state.list_keywords(product["site"], product["asin"], sid=product["sid"])
                            if row["tracking"]["state"] == "active"]
                    rank_result = collect_rank_history(sf, product["site"], product["asin"], today,
                                                       {row["keyword"] for row in core}) if core else {
                                                           "state": "no_core", "observations": [], "campaigns": 0,
                                                           "windows_completed": 0}
                    core_ids = {row["normalized"]: row["id"] for row in core}
                    for observation in rank_result["observations"]:
                        keyword_id = core_ids.get(observation["normalized"])
                        if keyword_id:
                            rank = observation["rank"]
                            rank_state = "absolute_rank" if rank is not None else (
                                "reported_position" if observation["channel"] == "advertising" else "conflicting")
                            label = observation["display"]
                            if observation["source_group"]:
                                label = f"{label or '广告位'} · 组 {observation['source_group']}"
                            state.record_rank(keyword_id, observation["date"], observation["channel"], rank,
                                              rank_state, run_id, display=label)
                    for member in members:
                        keyword_snapshot[member["key"]]["rank_history_state"] = rank_result["state"]
                        keyword_snapshot[member["key"]]["rank_windows_completed"] = rank_result["windows_completed"]
                        keyword_snapshot[member["key"]]["rank_campaigns"] = rank_result["campaigns"]
                        keyword_snapshot[member["key"]]["rank_campaigns_probed"] = rank_result.get("campaigns_probed", 0)
                        keyword_snapshot[member["key"]]["rank_terms_two_week"] = rank_result.get("two_week_terms", 0)
                        keyword_snapshot[member["key"]]["rank_natural_terms_two_week"] = rank_result.get("natural_two_week_terms", 0)
                        keyword_snapshot[member["key"]]["rank_ad_terms_two_week"] = rank_result.get("ad_two_week_terms", 0)
                        keyword_snapshot[member["key"]]["rank_campaign_audit"] = rank_result.get("campaign_audit", [])
                        keyword_snapshot[member["key"]]["rank_error_types"] = rank_result.get("error_types", [])
                else:
                    for member in members:
                        keyword_snapshot[member["key"]]["rank_history_state"] = "deferred_rank_budget"
                terms = [row["keyword"] for row in state.list_keywords(product["site"], product["asin"], sid=product["sid"])
                         if row["tracking"]["state"] == "active"]
                if terms:
                    demand_by_product[key] = {}
                    failed_batches = 0
                    for term_batch in keyword_batches(terms):
                        try:
                            history = sf.call("market_get_keyword_history", {"keywords": term_batch,
                                                                              "country": product["site"], "granularity": "week"})
                        except Exception as exc:
                            failed_batches += 1
                            keyword_snapshot[key]["sif_history_error_type"] = type(exc).__name__
                            continue
                        for entry in _sif_terms(history):
                            term = normalize_keyword(str(entry.get("keyword") or ""))
                            latest = entry.get("latest") if isinstance(entry.get("latest"), dict) else {}
                            if term and latest:
                                demand_by_product[key][term] = {"weekly_volume": number(latest.get("volume")),
                                                                "volume_period": latest.get("date"),
                                                                "aba_rank": number(latest.get("rank"))}
                    volume_state = "partial" if failed_batches else "verified" if demand_by_product[key] else "no_rows"
                    for member in members:
                        demand_by_product[member["key"]] = demand_by_product[key]
                        keyword_snapshot[member["key"]]["sif_history_state"] = volume_state
                        keyword_snapshot[member["key"]]["sif_history_batches_failed"] = failed_batches
            sif_states = [keyword_snapshot[p["key"]]["sif_state"] for p in products.values() if p["status"] == "1"]
            status["sif"] = {"state": "partial" if any(value in {"source_failed", "replay_missing", "deferred_after_repeated_failures", "not_queued"} for value in sif_states) else "verified",
                             "queried_products": sum(value in {"verified", "no_rows", "source_failed", "replay_missing"} for value in sif_states),
                             "successful_products": sum(value in {"verified", "no_rows"} for value in sif_states),
                             "deferred_products": sum(value in {"deferred_after_repeated_failures", "not_queued"} for value in sif_states),
                             "replay_missing_products": sum(value == "replay_missing" for value in sif_states),
                             "eligible_unique_asins": queue["eligible"],
                             "selected_unique_asins": len(queue["selected"]),
                             "rank_attempt_limit": sif_budget.rank_limit,
                             "rank_attempts": sif_budget.rank_attempts,
                             "total_active": queue["active"]}
        else:
            status["sif"] = {"state": "not_configured"}
        rank_by_product = {}
        for product in products.values():
            for term in state.list_keywords(product["site"], product["asin"], sid=product["sid"]):
                observations = state.rank_window(term["id"], rank_window[0], rank_window[1], run_id=run_id)
                rank_by_product[(product["key"], term["normalized"])] = summarize_rank_evidence(
                    observations, rank_window)
        bid_actions = target_bid_reviews(target_rows, products, links, profiles, rank_by_product,
                                         negative_actions=actions)
        actions.extend(bid_actions)
        status["ads_diagnosis"]["bid_review_candidates"] = len(bid_actions)
        for product in products.values():
            key = product["key"]
            related = [action for action in actions if product["asin"] in action["affected_asins"] and profiles.get(action["profile_id"]) == product["sid"]]
            inv = inventory_issues(product)
            listing = listing_issues(product)
            ad_issues = [{"domain": "advertising", "type": action["kind"], "severity": "medium" if action["kind"] != "negative" else "high",
                          "title": {"negative": "否词待确认", "negative_asin": "ASIN 否定待确认",
                                    "exact": "精准投放待确认", "observe": "搜索词观察",
                                    "bid_review": "竞价复核"}[action["kind"]],
                          "hypothesis": action["reason"], "evidence": {"clicks": action["clicks"], "spend": action["spend"],
                                                                "orders": action["orders"], "sales": action["sales"], "acos": action["acos"]},
                          "gaps": [], "actionability": 1, "action_key": action["action_key"]}
                         for action in related if action["reviewable"]]
            product["issues"] = prioritize(inv + listing + ad_issues)
            product["actions"] = related
            parent_asin = str(product.get("parent_asin") or product["asin"]).upper()
            keyword_snapshot[key]["competitors"] = state.list_competitors(product["sid"], product["site"], parent_asin)
            current_gap_words = {normalize_keyword(word) for word in
                                 (keyword_snapshot[key].get("competitor_discovery") or {}).get("candidate_keywords", [])}
            keyword_snapshot[key]["terms"] = [
                {**term, **demand_by_product.get(key, {}).get(term["normalized"], {}),
                 **signals_by_product.get(key, {}).get(term["normalized"], {}),
                 "internal_evidence": internal_evidence.get(key, {}).get(term["normalized"]),
                 "keyword_targets": target_evidence.get(key, {}).get(term["normalized"], []),
                 "target_catalog_complete": False,
                 "current_competitor_gap": term["normalized"] in current_gap_words,
                 "opportunity_state": ("internal_evidence" if term["normalized"] in internal_evidence.get(key, {})
                                        else "external_candidate_unverified" if "sif_asin_signals" in term.get("sources", [])
                                             or term["normalized"] in current_gap_words
                                        else "tracked_without_current_ads"),
                 "rank_window": rank_window,
                 "rank_observations": state.rank_window(term["id"], rank_window[0], rank_window[1], run_id=run_id),
                 "rank_14d_state": keyword_snapshot[key].get("rank_history_state") or "current_snapshot_only"}
                for term in state.list_keywords(product["site"], product["asin"], sid=product["sid"])
            ]
            product["keyword_state"] = keyword_snapshot[key]
        if sif and getattr(sif, "transport_state", None) in {
                "same_day_b_raw_resume_live", "same_day_b_complete_extend_live"}:
            status["sif_transport"].update({"reused_calls": sif.replayed_calls,
                                            "live_calls": sif.live_calls})
        if sif and hasattr(sif, "cache_hits"):
            status["sif_cache"] = {"hits": sif.cache_hits, "miss_calls": sif.live_calls, "request_limit": sif.max_calls}
        board = {"schema": "amazon-ops-b/1", "run_id": run_id, "as_of_date": today.isoformat(),
                 "fetched_at": datetime.now(timezone.utc).isoformat(),
                 "weeks": weeks, "periods": {"search_terms": [start, end], "sif_rank": rank_window},
                 "status": status, "coverage": {**gaps, "products": len(products),
                                                "active": sum(p["status"] == "1" for p in products.values()),
                                                "problem": sum(p["status"] == "1" and any(i["severity"] != "gap" for i in p["issues"]) for p in products.values()),
                                                "actions": sum(a["executable"] for a in actions)},
                 "products": products, "actions": actions, "profile_to_sid": profiles,
                 "ad_keyword_targets": target_rows,
                 "keyword_snapshot": keyword_snapshot}
        batch_hash = _write_json(run_dir / "board.json", board)
        manifest = {"run_id": run_id, "state": "staged", "fetched_at": board["fetched_at"],
                    "batch_sha256": batch_hash, "source_calls": ledger, "source_status": status,
                    "counts": board["coverage"]}
        _write_json(run_dir / "manifest.json", manifest)
        state_path.parent.mkdir(parents=True, exist_ok=True)
        if _state_digest(state_path) != source_state_digest:
            raise RuntimeError("local review or keyword state changed during refresh; staged run not published")
        os.replace(staged_state_path, state_path)
        manifest["state"] = "complete"
        _write_json(run_dir / "manifest.json", manifest)
        _write_json(root / "storage" / "state" / "latest_complete.json", {"run_id": run_id, "batch_sha256": batch_hash})
        return {"run_id": run_id, "run_dir": str(run_dir), "coverage": board["coverage"], "status": status}
    except Exception as exc:
        _write_json(run_dir / "manifest.json", {"run_id": run_id, "state": "failed", "error_type": type(exc).__name__,
                                                      "message": str(exc)[:180], "source_calls": ledger, "source_status": status})
        raise


def refresh(root, lingxing, sif, **kwargs):
    from b_ops.run_lock import single_writer
    with single_writer(Path(root)):
        return _refresh(Path(root), lingxing, sif, **kwargs)
