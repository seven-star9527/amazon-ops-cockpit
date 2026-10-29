"""Normalize actual dated SIF campaign keyword ranks; never fill missing days."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
import re

from b_ops.collect.replay import ReplayMissing
from b_ops.model.snapshot import number
from b_ops.model.storage import normalize_keyword


def current_rank_fields(row: dict) -> dict:
    """Preserve SIF page/position text; only a plain positive number is absolute."""
    raw = row.get("organic_rank")
    numeric = number(raw)
    numeric = numeric if numeric is not None and numeric > 0 else None
    return {"natural_rank": numeric,
            "natural_rank_display": str(raw).strip() if raw is not None and numeric is None else None,
            "ad_rank_display": str(row.get("sp_rank") or "").strip() or None}


def recent_rank_windows(today: str | date) -> list[tuple[str, str]]:
    current = date.fromisoformat(today) if isinstance(today, str) else today
    available = current - timedelta(days=1)
    end = available - timedelta(days=(available.weekday() - 5) % 7)
    start = end - timedelta(days=13)
    return [(start.isoformat(), (start + timedelta(days=6)).isoformat()),
            ((start + timedelta(days=7)).isoformat(), end.isoformat())]


def _point(value):
    if not isinstance(value, dict):
        return None, None
    rank = number(value.get("rank"))
    if rank is None or rank <= 0:
        rank = None
    label = str(value.get("rankLabel") or "").strip() or None
    return rank, label


def _asin(value) -> str | None:
    text = str(value or "").upper()
    match = re.search(r"(?<![A-Z0-9])B[A-Z0-9]{9}(?![A-Z0-9])", text)
    return match.group(0) if match else None


def parse_campaign_rank_history(payload: dict, target_asin: str, campaign_id: str) -> list[dict]:
    items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        return []
    target_asin = target_asin.upper()
    result = []
    for item in items:
        if not isinstance(item, dict):
            continue
        keyword = str(item.get("keyword") or "").strip()
        if not normalize_keyword(keyword):
            continue
        natural = item.get("naturalRankHistory") or {}
        variants = natural.get("variants") or []
        variant = next((part for part in variants if _asin(part.get("asin")) == target_asin), None)
        if variant:
            for day, point in zip(natural.get("dates") or [], variant.get("points") or []):
                rank, label = _point(point)
                if rank is not None and isinstance(day, str) and len(day) == 10:
                    result.append({"keyword": keyword, "normalized": normalize_keyword(keyword),
                                   "date": day, "channel": "natural", "rank": rank, "display": label,
                                   "source_campaign": campaign_id, "source_group": None})
        exposed = {str(group.get("adGroupId") or "") for group in item.get("exposedAdGroups") or []
                   if any(_asin(v.get("asin")) == target_asin for v in group.get("variants") or [])}
        ad_history = item.get("adRankHistory") or {}
        for group in ad_history.get("adGroups") or []:
            group_id = str(group.get("adGroupId") or "")
            if not group_id or group_id not in exposed:
                continue
            for day, point in zip(ad_history.get("dates") or [], group.get("points") or []):
                rank, label = _point(point)
                if (rank is not None or label) and isinstance(day, str) and len(day) == 10:
                    result.append({"keyword": keyword, "normalized": normalize_keyword(keyword),
                                   "date": day, "channel": "advertising", "rank": rank, "display": label,
                                   "source_campaign": campaign_id, "source_group": group_id})
    return result


def choose_rank_observations(rows: list[dict]) -> list[dict]:
    """One display point per term/day/channel; best observed ad group remains traceable."""
    chosen = {}
    for row in rows:
        key = row["normalized"], row["date"], row["channel"]
        current = chosen.get(key)
        if current is None or (row["channel"] == "advertising" and row["rank"] is not None and
                               (current["rank"] is None or row["rank"] < current["rank"])):
            chosen[key] = row
        elif row["channel"] == "natural" and row["rank"] is not None and current["rank"] != row["rank"]:
            chosen[key] = {**current, "rank": None, "display": "来源排名冲突"}
    return list(chosen.values())


def collect_rank_history(client, site: str, asin: str, today: str | date,
                         tracked_terms: set[str], *, campaign_limit: int = 4,
                         probe_limit: int = 8) -> dict:
    windows = recent_rank_windows(today)
    tracked = {normalize_keyword(term) for term in tracked_terms}
    try:
        overview = client.call("ads_get_asin_campaign_contribution_overview", {
            "asin": asin, "country": site, "start_date": windows[0][0],
            "end_date": windows[-1][1], "limit": 20})
    except ReplayMissing:
        return {"state": "replay_missing", "error_type": "ReplayMissing",
                "observations": [], "campaigns": 0, "windows_completed": 0}
    except Exception as exc:
        return {"state": "source_failed", "error_type": type(exc).__name__,
                "observations": [], "campaigns": 0, "windows_completed": 0}
    campaigns = overview.get("campaigns") if isinstance(overview, dict) else None
    if not isinstance(campaigns, list):
        return {"state": "shape_mismatch", "observations": [], "campaigns": 0, "windows_completed": 0}
    candidates = sorted((row for row in campaigns if isinstance(row, dict)), key=lambda row: (
        0 if str(row.get("ad_type") or "SP").upper() == "SP" else 1,
        -(number(row.get("contribution_score")) or 0)))
    seen = set()
    unique_candidates = []
    for row in candidates:
        campaign = str(row.get("campaign_display_id") or row.get("campaign_id") or "")
        if campaign and campaign not in seen:
            seen.add(campaign)
            unique_candidates.append(row)
    candidates = unique_candidates[:max(0, probe_limit)]
    if not candidates:
        return {"state": "no_campaign", "observations": [], "campaigns": 0, "windows_completed": 0}
    current_rows = []
    completed = 0
    failures = []
    audit = []
    campaign_terms = {}

    def read_window(campaign: str, period: tuple[str, str]) -> list[dict] | None:
        nonlocal completed
        try:
            response = client.call("ads_get_campaign_contribution_breakdown", {
                "asin": asin, "campaignId": campaign, "start_date": period[0],
                "end_date": period[1], "breakdown_by": "keyword", "limit": 100,
                "country": site})
            completed += 1
            return [row for row in parse_campaign_rank_history(response, asin, campaign)
                    if row["normalized"] in tracked]
        except Exception as exc:
            failures.append(type(exc).__name__)
            return None

    for candidate in candidates:
        campaign = str(candidate.get("campaign_display_id") or candidate.get("campaign_id"))
        rows = read_window(campaign, windows[1])
        rows = rows or []
        current_rows.extend(rows)
        natural_days = defaultdict(set)
        any_days = defaultdict(set)
        for row in rows:
            if row["rank"] is not None:
                any_days[row["normalized"]].add(row["date"])
                if row["channel"] == "natural":
                    natural_days[row["normalized"]].add(row["date"])
        natural_terms = {term for term, days in natural_days.items() if len(days) >= 5}
        any_terms = {term for term, days in any_days.items() if len(days) >= 5}
        campaign_terms[campaign] = (natural_terms, any_terms)
        audit.append({"campaign": campaign, "ad_type": candidate.get("ad_type"),
                      "contribution_score": number(candidate.get("contribution_score")),
                      "current_points": len(rows), "natural_terms": len(natural_terms),
                      "ranked_terms": len(any_terms), "selected_for_previous": False})
    # Several high-contribution campaigns can show the same terms. Re-rank
    # after each previous-week response: a campaign with no prior observations
    # must not crowd out a second source for the same natural keyword.
    remaining = [entry for entry in audit if entry["current_points"]]
    selected = []
    previous_rows = []
    coverage_target = min(10, len(tracked))
    qualified = set()

    def qualified_channels(rows: list[dict]) -> set[tuple[str, str]]:
        days_by_term = defaultdict(lambda: [set(), set()])
        for row in choose_rank_observations(rows):
            if row["rank"] is not None:
                week_index = 0 if row["date"] <= windows[0][1] else 1
                days_by_term[(row["normalized"], row["channel"])][week_index].add(row["date"])
        return {(term, channel) for (term, channel), (previous, current) in days_by_term.items()
                if len(previous) >= 5 and len(current) >= 5}

    while remaining and len(selected) < max(0, campaign_limit):
        covered_natural = {term for term, channel in qualified if channel == "natural"}
        covered_any = {term for term, _ in qualified}
        entry = max(remaining, key=lambda candidate: (
            len(campaign_terms[candidate["campaign"]][0] - covered_natural),
            len(campaign_terms[candidate["campaign"]][1] - covered_any),
            candidate["natural_terms"], candidate["ranked_terms"],
            candidate["current_points"], candidate["contribution_score"] or 0))
        remaining.remove(entry)
        selected.append(entry)
        entry["selected_for_previous"] = True
        previous_rows.extend(read_window(entry["campaign"], windows[0]) or [])
        qualified = qualified_channels(current_rows + previous_rows)
        if len({term for term, _ in qualified}) >= coverage_target:
            break
    deduped = choose_rank_observations(current_rows + previous_rows)
    natural_two_week_terms = len({term for term, channel in qualified if channel == "natural"})
    ad_two_week_terms = len({term for term, channel in qualified if channel == "advertising"})
    two_week_terms = len({term for term, _ in qualified})
    state = ("replay_missing" if failures and not completed and set(failures) == {"ReplayMissing"} else
             "source_failed" if failures and not completed else
             "no_rows" if not deduped and not failures else
             "verified" if two_week_terms >= coverage_target and not failures else "partial")
    return {"state": state, "observations": deduped, "campaigns": len(selected),
            "campaigns_probed": len(audit), "campaign_audit": audit,
            "windows_completed": completed, "windows_expected": len(audit) + len(selected),
            "two_week_terms": two_week_terms, "natural_two_week_terms": natural_two_week_terms,
            "ad_two_week_terms": ad_two_week_terms, "tracked_terms": len(tracked),
            "error_types": sorted(set(failures))}
