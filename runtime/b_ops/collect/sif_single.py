"""Opt-in, read-only SIF refresh for one ASIN beside an immutable B batch."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import uuid4

from b_ops.collect.refresh import RecordedSif, _sif_terms, signal_market_fields
from b_ops.collect.sif_queue import keyword_batches
from b_ops.collect.sif_ranks import collect_rank_history, current_rank_fields, recent_rank_windows
from b_ops.model.snapshot import number
from b_ops.model.storage import StateStore, normalize_keyword


def query_single_sif(client, state: StateStore, run_dir: Path, product: dict,
                     *, today: date | None = None) -> dict:
    today = today or date.today()
    query_id = "sif-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-") + uuid4().hex[:6]
    target = Path(run_dir) / "supplements" / query_id
    target.mkdir(parents=True, exist_ok=False)
    ledger = []
    sif = RecordedSif(client, target, query_id, ledger)
    site, asin, sid = product["site"], product["asin"], str(product["sid"])
    windows = recent_rank_windows(today)
    rank_window = [windows[0][0], windows[-1][1]]
    signals = _sif_terms(sif.call("market_get_asin_keyword_signals", {
        "asin": asin, "country": site, "time_type": "lately", "time_value": "7", "topN": 50}))
    current = {normalize_keyword(row["keyword"]): row for row in state.list_keywords(site, asin, sid=sid)}
    signal_by_word = {}
    for row in signals[:30]:
        keyword = str(row.get("keyword") or row.get("word") or "").strip()
        if keyword:
            signal_by_word[normalize_keyword(keyword)] = row
    terms = {row["keyword"] for row in current.values() if row.get("tracking", {}).get("state") == "active"}
    terms.update(str(row.get("keyword") or row.get("word")) for row in signal_by_word.values())
    rank = collect_rank_history(sif, site, asin, today, terms)
    demand = {}
    failed_history = 0
    for batch in keyword_batches(sorted(terms)):
        try:
            history = _sif_terms(sif.call("market_get_keyword_history", {
                "keywords": batch, "country": site, "granularity": "week"}))
            for row in history:
                word = normalize_keyword(str(row.get("keyword") or ""))
                latest = row.get("latest") if isinstance(row.get("latest"), dict) else {}
                if word and latest:
                    demand[word] = {"weekly_volume": number(latest.get("volume")),
                                    "volume_period": latest.get("date"),
                                    "aba_rank": number(latest.get("rank"))}
        except Exception:
            failed_history += 1
    signal_ids = {}
    for word, row in signal_by_word.items():
        key = state.add_keyword(site, asin, str(row.get("keyword") or row.get("word")),
                                "sif_asin_signals", "单 ASIN 手动查询", query_id, sid)
        state.mark_sif_core(key, sid, query_id)
        signal_ids[word] = key
    for word, row in signal_by_word.items():
        key = signal_ids[word]
        natural = current_rank_fields(row)
        natural_date = str(row.get("organic_rank_time_us") or "")
        ad_date = str(row.get("sp_rank_time_us") or "")
        if len(natural_date) >= 10:
            if natural["natural_rank"] is not None:
                state.record_rank(key, natural_date[:10], "natural", natural["natural_rank"],
                                  "absolute_rank", query_id)
            elif natural["natural_rank_display"]:
                state.record_rank(key, natural_date[:10], "natural", None, "reported_position",
                                  query_id, display=natural["natural_rank_display"])
        if natural["ad_rank_display"] and len(ad_date) >= 10:
            state.record_rank(key, ad_date[:10], "advertising", None, "reported_position",
                              query_id, display=natural["ad_rank_display"])
    core_ids = {row["normalized"]: row["id"] for row in state.list_keywords(site, asin, sid=sid)}
    for observation in rank["observations"]:
        key = core_ids.get(observation["normalized"])
        if key:
            state.record_rank(key, observation["date"], observation["channel"], observation["rank"],
                              "absolute_rank" if observation["rank"] is not None else
                              "reported_position" if observation["channel"] == "advertising" else "conflicting",
                              query_id, display=observation["display"])
    state.record_sif_fetch(site, asin, query_id, "verified" if signals else "no_rows")
    snapshot = []
    for term in state.list_keywords(site, asin, sid=sid):
        signal = signal_by_word.get(term["normalized"], {})
        snapshot.append({**term, **demand.get(term["normalized"], {}),
                         **current_rank_fields(signal),
                         **signal_market_fields(signal),
                         "rank_as_of_date": today.isoformat(),
                         "rank_window": rank_window,
                         "rank_14d_state": rank["state"],
                         "rank_observations": state.rank_window(
                             term["id"], rank_window[0], rank_window[1], run_id=query_id)})
    result = {"run_id": Path(run_dir).name, "query_id": query_id, "queried_at": datetime.now(timezone.utc).isoformat(),
              "as_of_date": today.isoformat(), "sid": sid, "site": site, "asin": asin,
              "signals": len(signal_by_word), "rank_state": rank["state"],
              "rank_window": rank_window,
              "rank_terms_two_week": rank.get("two_week_terms", 0),
              "rank_natural_terms_two_week": rank.get("natural_two_week_terms", 0),
              "rank_ad_terms_two_week": rank.get("ad_two_week_terms", 0),
              "rank_campaign_audit": rank.get("campaign_audit", []),
              "rank_windows_completed": rank["windows_completed"],
              "history_failed_batches": failed_history, "terms": snapshot,
              "source_calls": ledger}
    (target / "summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result
