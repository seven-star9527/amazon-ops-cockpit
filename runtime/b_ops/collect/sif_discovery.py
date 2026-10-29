"""Bounded SIF competitor discovery; all findings remain external evidence."""

from __future__ import annotations

import re
from html import unescape

from b_ops.model.storage import normalize_keyword


_ASIN = re.compile(r"(?<![A-Z0-9])B[A-Z0-9]{9}(?![A-Z0-9])", re.I)
_WORDS = re.compile(r"[a-z0-9]+")
_STOP = {"the", "and", "with", "for", "from", "set", "sets", "of", "a", "an", "pcs",
         "piece", "pieces", "in", "to", "by", "pack", "colour", "color", "green"}
_BROAD_CATEGORIES = {"toys & games", "home & kitchen", "computers & accessories",
                     "health & personal care", "baby products", "sports & outdoors",
                     "beauty", "pet supplies", "office products", "automotive"}


def competitor_asin(value: object) -> str | None:
    match = _ASIN.search(str(value or ""))
    return match.group(0).upper() if match else None


def _title_words(value: object) -> set[str]:
    words = set()
    for token in _WORDS.findall(unescape(str(value or "")).lower()):
        if token in _STOP or len(token) < 3:
            continue
        words.add({"learning": "learn", "learns": "learn", "knives": "knife",
                   "cooking": "cook", "children": "child"}.get(token, token))
    return words


def choose_competitor_seed(signals: list[dict], target_title: str) -> str:
    """Prefer a product-intent phrase over a high-share but ambiguous root."""
    target = _title_words(target_title)
    anchor = next((word for word in ("knife", "tablet", "keyboard", "scissor", "backpack", "bottle")
                   if word in target), None)
    scored = []
    for row in signals:
        word = str(row.get("keyword") or row.get("word") or "").strip()
        tokens = _title_words(word)
        overlap = len(tokens & target)
        if word and overlap >= 2:
            scored.append((int(anchor in tokens) if anchor else 0, overlap,
                           min(len(tokens), 5), float(row.get("traffic_share") or 0), word))
    return max(scored)[-1] if scored else ""


def _profile_summary(row: dict) -> dict:
    categories = [str(item.get("category_name") or "").strip() for item in row.get("bsr_list") or []
                  if isinstance(item, dict) and item.get("category_name")]
    image = str(row.get("img") or "")
    return {"title": unescape(str(row.get("title") or "")).strip(),
            "brand": str(row.get("brand") or "").removeprefix("Brand: ").strip(),
            "image_url": image if image.startswith("https://m.media-amazon.com/images/") else None,
            "price": row.get("price"), "rating": row.get("star_rating"),
            "reviews": row.get("rating_num"), "monthly_orders": row.get("bought_in_past_month"),
            "categories": categories}


def _relevance(target: dict, candidate: dict, *, target_price: float | None) -> tuple[str, str]:
    if not candidate or not candidate.get("title"):
        return "profile_missing", "SIF 未返回商品资料，暂不据此扩展机会词"
    anchor = next((word for word in ("knife", "tablet", "keyboard", "scissor", "backpack", "bottle")
                   if word in _title_words(target.get("title"))), None)
    if anchor and anchor not in _title_words(candidate.get("title")):
        return "intent_mismatch", "缺少本品的核心商品类型词，不纳入自动竞品查询"
    target_categories = {x.lower() for x in target.get("categories") or []}
    other_categories = {x.lower() for x in candidate.get("categories") or []}
    if target_categories and other_categories and not (target_categories & other_categories):
        return "category_mismatch", "与本品商品类目不同，排除自动竞品比较"
    broad_target = target_categories & _BROAD_CATEGORIES
    broad_other = other_categories & _BROAD_CATEGORIES
    if not target_categories or not other_categories or (broad_target and not broad_other):
        return "category_unverified", "缺少可比的类目证据，待运营判断"
    try:
        ratio = float(candidate.get("price")) / float(target_price)
    except (TypeError, ValueError, ZeroDivisionError):
        return "price_unverified", "价格不可比，待运营判断"
    if ratio < 0.4 or ratio > 2.5:
        return "price_gap", "价格带差异过大，暂不自动用作直接竞品"
    overlap = _title_words(target.get("title")) & _title_words(candidate.get("title"))
    if len(overlap) < 2:
        return "intent_mismatch", "标题中的商品意图不足以证明可比，待运营判断"
    return "plausible", "类目、价格带和商品意图初筛一致；仍需运营复核"


def discover_competitors(client, *, site: str, asin: str, seed: str, limit: int = 3,
                         price: float | None = None) -> list[dict]:
    limit = min(max(int(limit), 0), 10)
    if not limit or not seed.strip():
        return []
    params = {
        "keyword": seed.strip(), "country": site.upper(), "my_asin": asin.upper(), "max_results": limit,
    }
    if price is not None and price > 0:
        params.update({"price_min": round(price * 0.4, 2), "price_max": round(price * 2.5, 2)})
    data = client.call("market_discover_competitors", params)
    raw = data.get("competitors") if isinstance(data, dict) else []
    result, seen = [], {asin.upper()}
    for row in raw if isinstance(raw, list) else []:
        if not isinstance(row, dict):
            continue
        candidate = competitor_asin(row.get("asin") or row.get("url"))
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        result.append({"asin": candidate, "source": "sif_serp_discovery", "seed": seed.strip(),
                       "monthly_orders": row.get("monthly_orders"), "url": row.get("url"),
                       "price": row.get("price"), "reviews": row.get("review_count"),
                       "posture": row.get("posture"), "serp_share": row.get("serp_share")})
        if len(result) >= limit:
            break
    return result


def competitor_gap_terms(client, *, site: str, competitor: str, own_terms: set[str],
                         max_terms: int = 10) -> list[dict]:
    candidate = competitor_asin(competitor)
    if not candidate:
        raise ValueError("invalid competitor ASIN")
    data = client.call("market_get_asin_keyword_signals", {
        "asin": candidate, "country": site.upper(), "time_type": "lately", "time_value": "7",
        "topN": min(max(int(max_terms), 1), 50),
    })
    rows = data.get("top_keywords") or data.get("keywords") or data.get("data") or [] if isinstance(data, dict) else []
    own = {normalize_keyword(word) for word in own_terms}
    seen, result = set(), []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        keyword = str(row.get("keyword") or row.get("word") or "").strip()
        normalized = normalize_keyword(keyword)
        if not normalized or normalized in own or normalized in seen:
            continue
        seen.add(normalized)
        result.append({"keyword": keyword, "source": "sif_competitor_gap",
                       "competitor_asin": candidate, "target_state": "unverified",
                       "traffic_share": row.get("traffic_share")})
        if len(result) >= max_terms:
            break
    return result


def collect_competitor_pool(client, state, *, sid: str, site: str, parent_asin: str,
                            asin: str, seed: str, run_id: str, own_terms: set[str],
                            max_competitors: int = 3, target_title: str = "",
                            target_price: float | None = None) -> dict:
    """Discover at parent grain, but bind candidate terms to the viewed child ASIN.

    The pool is external-only: a gap is neither an Exact target nor an active core word.
    Caller records failures and source ledger; this function never silently substitutes
    a different competitor or treats empty signals as proof of absence.
    """
    max_competitors = min(max(int(max_competitors), 0), 3)
    found = []
    discovery_state = "no_seed" if not seed.strip() else "verified"
    discovery_error_type = None
    discovery_error_hint = None
    discovery_error_status = None
    if seed.strip():
        try:
            found = discover_competitors(client, site=site, asin=asin, seed=seed, limit=10,
                                         price=target_price)
        except Exception as exc:
            discovery_state = "replay_missing" if type(exc).__name__ == "ReplayMissing" else "source_failed"
            discovery_error_type = type(exc).__name__
            discovery_error_hint = getattr(exc, "error_hint", None)
            discovery_error_status = getattr(exc, "status_code", None)
    saved = state.list_competitors(sid, site, parent_asin)
    manual = [row for row in saved if row["active"] and row["origin"] == "operator"]
    suppressed = {row["asin"] for row in saved if not row["active"] and row["origin"] == "operator"}
    candidate_by_asin = {row["asin"]: dict(row) for row in found if row["asin"] not in suppressed}
    for row in manual:
        candidate_by_asin.setdefault(row["asin"], {"asin": row["asin"]})["source"] = "operator"
    profile_state = "verified"
    profiles = {}
    if candidate_by_asin:
        try:
            response = client.call("market_get_asin_profile", {
                "asins": [asin.upper(), *candidate_by_asin], "country": site.upper()})
            for item in response.get("list") or [] if isinstance(response, dict) else []:
                identity = competitor_asin(item.get("asin")) if isinstance(item, dict) else None
                if identity:
                    profiles[identity] = _profile_summary(item)
        except Exception as exc:
            profile_state = "replay_missing" if type(exc).__name__ == "ReplayMissing" else "source_failed"
    target = profiles.get(asin.upper()) or {"title": target_title, "categories": []}
    if not target.get("title"):
        target["title"] = target_title
    basis_price = target_price or target.get("price")
    candidates, selection = [], []
    for value in sorted(candidate_by_asin.values(), key=lambda row: row.get("source") != "operator"):
        candidate = profiles.get(value["asin"]) or {}
        if value.get("source") == "operator":
            relevance_state, reason = "operator_selected", "运营手动维护；外部机会词仍需逐词核验"
        else:
            relevance_state, reason = _relevance(target, candidate, target_price=basis_price)
        item = {**value, **candidate, "asin": value["asin"], "relevance_state": relevance_state,
                "relevance_reason": reason, "selected": False}
        candidates.append(item)
        if relevance_state in {"plausible", "operator_selected"} and len(selection) < max_competitors:
            item["selected"] = True
            selection.append(item)
    root_state = "not_needed"
    if not selection and seed.strip() and discovery_state == "verified":
        root_state = "verified"
        try:
            root = client.call("market_get_keyword_root_competitors", {
                "keyword_root": seed, "country": site.upper(), "topN": 10})
            root_rows = []
            existing = set(candidate_by_asin) | suppressed | {asin.upper()}
            for entry in root.get("competitors") or [] if isinstance(root, dict) else []:
                candidate = competitor_asin(entry.get("asin")) if isinstance(entry, dict) else None
                if candidate and candidate not in existing:
                    root_rows.append({"asin": candidate, "source": "sif_keyword_root", "seed": seed,
                                      "covered_volume": entry.get("covered_volume")})
                    existing.add(candidate)
            if root_rows:
                profile = client.call("market_get_asin_profile", {
                    "asins": [asin.upper(), *[entry["asin"] for entry in root_rows[:10]]],
                    "country": site.upper()})
                for entry in profile.get("list") or [] if isinstance(profile, dict) else []:
                    identity = competitor_asin(entry.get("asin")) if isinstance(entry, dict) else None
                    if identity:
                        profiles[identity] = _profile_summary(entry)
                for entry in root_rows:
                    data = profiles.get(entry["asin"]) or {}
                    relevance_state, reason = _relevance(target, data, target_price=basis_price)
                    candidate = {**entry, **data, "relevance_state": relevance_state,
                                 "relevance_reason": reason, "selected": False}
                    candidates.append(candidate)
                    if relevance_state == "plausible" and len(selection) < max_competitors:
                        candidate["selected"] = True
                        selection.append(candidate)
        except Exception as exc:
            root_state = "replay_missing" if type(exc).__name__ == "ReplayMissing" else "source_failed"
    state.upsert_discovered_competitors(sid, site, parent_asin,
                                        [row["asin"] for row in selection if row["source"] != "operator"], run_id)
    candidate_rows, competitor_rows = [], []
    for competitor in selection:
        row = {"asin": competitor["asin"], "origin": competitor["source"],
               "state": "not_queried", "profile": {key: competitor.get(key) for key in
                    ("title", "brand", "image_url", "price", "rating", "reviews", "monthly_orders", "categories")},
               "relevance_state": competitor["relevance_state"]}
        try:
            gaps = competitor_gap_terms(client, site=site, competitor=competitor["asin"],
                                        own_terms=own_terms, max_terms=10)
            row["state"] = "verified" if gaps else "no_gap_rows"
            row["gap_terms"] = len(gaps)
            candidate_rows.extend(gaps)
        except Exception as exc:
            row["state"] = "replay_missing" if type(exc).__name__ == "ReplayMissing" else "source_failed"
            row["error_type"] = type(exc).__name__
        competitor_rows.append(row)
    for term in candidate_rows:
        state.add_keyword(site, asin, term["keyword"], "sif_competitor_gap",
                          f"竞品 {term['competitor_asin']} 的 SIF 关键词信号；内部投放仍待核对", run_id, sid)
    return {"state": "partial" if discovery_state in {"source_failed", "replay_missing"} or
            profile_state in {"source_failed", "replay_missing"} or
            root_state in {"source_failed", "replay_missing"} or
            any(row["state"] in {"source_failed", "replay_missing"} for row in competitor_rows)
            else "verified" if competitor_rows else "no_competitors",
            "seed": seed, "discovery_state": discovery_state, "root_state": root_state,
            "discovery_error_type": discovery_error_type, "profile_state": profile_state,
            "discovery_error_hint": discovery_error_hint, "discovery_error_status": discovery_error_status,
            "competitors": competitor_rows, "candidate_terms": len(candidate_rows),
            "candidate_keywords": [row["keyword"] for row in candidate_rows],
            "candidates": candidates,
            "selection_limit": max_competitors}
