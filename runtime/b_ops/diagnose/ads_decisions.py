"""B-line ad-group/target decision adapter around the installed specialist.

The specialist classifies search-term evidence. This layer only maps its scope
to group actions and adds conservative, read-only target bid review candidates.
"""

from __future__ import annotations

import re
from datetime import date, timedelta

from b_ops.model.storage import normalize_keyword


def _catalog(products: dict, profile_to_sid: dict[str, str]) -> dict:
    return {(product["sid"], product["asin"]): product for product in products.values()
            if product.get("sid") and product.get("asin")}


def _parent_scope(profile_id: str, asins: list[str], catalog: dict,
                  profile_to_sid: dict[str, str]) -> str:
    sid = profile_to_sid.get(profile_id)
    if not sid or not asins:
        return "unmapped_promoted_asin"
    members = [catalog.get((sid, asin)) for asin in asins]
    if any(member is None for member in members):
        return "unmapped_promoted_asin"
    parents = {str(member.get("parent_asin") or member["asin"]).upper() for member in members}
    return "verified_same_parent" if len(parents) == 1 else "cross_parent_shared_group"


def group_scoped_actions(actions: list[dict], products: dict,
                         profile_to_sid: dict[str, str]) -> list[dict]:
    """Do not duplicate one group action across affected child ASIN views."""
    catalog = _catalog(products, profile_to_sid)
    result = []
    for action in actions:
        if action.get("kind") != "exact" or not action.get("source_scopes"):
            result.append(action)
            continue
        scopes = action["source_scopes"]
        for scope in scopes:
            affected = sorted({str(value).upper() for value in scope.get("related_asins") or []})
            parent_state = _parent_scope(action["profile_id"], affected, catalog, profile_to_sid)
            processed = str(action.get("processed_status") or "")
            source_block = str(action.get("blocked_reason") or "")
            blocked = parent_state if parent_state != "verified_same_parent" else ""
            if source_block in {"incomplete_source_coverage"}:
                blocked = source_block
            elif source_block and not affected:
                blocked = source_block
            reviewable = bool(not blocked and not processed and scope.get("sponsored_type") == "sp"
                              and all(scope.get(name) for name in ("profile_id", "campaign_id", "ad_group_id")))
            plan = dict(action.get("exact_plan") or {})
            if len(affected) > 1:
                # One same-parent group action, but no preselected destination.
                plan.update({"target_required": True, "target_campaign_id": "", "target_ad_group_id": "",
                             "blocked_reason": "operator_destination_required"})
            key = "exact-group|" + "|".join((str(scope.get("profile_id") or ""),
                       str(scope.get("campaign_id") or ""), str(scope.get("ad_group_id") or ""),
                       normalize_keyword(action.get("query") or "")))
            result.append({**action, "action_key": key,
                           "campaign_id": str(scope.get("campaign_id") or ""),
                           "campaign_name": str(scope.get("campaign_name") or ""),
                           "ad_group_id": str(scope.get("ad_group_id") or ""),
                           "ad_group_name": str(scope.get("ad_group_name") or ""),
                           "affected_asins": affected, "shared_group": len(affected) > 1,
                           "parent_scope": parent_state, "reviewable": reviewable,
                           "executable": False, "blocked_reason": blocked,
                           "clicks": scope.get("clicks", 0), "spend": scope.get("spends", 0),
                           "impressions": scope.get("impressions", 0), "orders": scope.get("orders", 0),
                           "sales": scope.get("sales", 0), "acos": scope.get("acos"),
                           "cpc": scope.get("cpc"), "cvr": scope.get("cvr"),
                           "record_ids": scope.get("source_record_ids", []),
                           "source_rows": scope.get("sources", []), "source_scopes": [scope],
                           "source_count": scope.get("source_count", 0), "exact_plan": plan})
    return result


def reconcile_exact_targets(actions: list[dict], targets: list[dict], group_links: dict,
                            products: dict, profile_to_sid: dict[str, str],
                            *, target_status: dict[str, dict]) -> list[dict]:
    """Positive report rows can prove a target exists; absent rows never prove none."""
    catalog = _catalog(products, profile_to_sid)
    result = []
    for action in actions:
        if action.get("kind") != "exact":
            result.append(action)
            continue
        row = dict(action)
        profile = row.get("profile_id")
        sid = profile_to_sid.get(profile)
        asins = row.get("affected_asins") or []
        parents = {str(catalog[(sid, asin)].get("parent_asin") or asin).upper()
                   for asin in asins if (sid, asin) in catalog}
        matching = []
        for target in targets:
            if target.get("profile_id") != profile or target.get("match_type") != "exact" or (
                    target.get("normalized_keyword") != row.get("normalized_keyword")):
                continue
            related = group_links.get((profile, target.get("ad_group_id")), set())
            target_parents = {str(catalog[(sid, asin)].get("parent_asin") or asin).upper()
                              for asin in related if (sid, asin) in catalog}
            if parents and target_parents and parents.intersection(target_parents):
                matching.append(target)
        active = [target for target in matching if all(target.get(field) == "enabled" for field in
                  ("target_state", "campaign_state", "ad_group_state"))]
        paused = [target for target in matching if target not in active]
        if active:
            row.update({"target_check": "active_exact_verified", "existing_target_ids":
                        [target["target_id"] for target in active], "processed_status": "already_exact_running",
                        "reviewable": False, "executable": False, "blocked_reason": "",
                        "existing_exact_matches": active, "exact_match_source": "keyword_target_report"})
        elif paused:
            row.update({"target_check": "paused_exact_verified", "existing_target_ids":
                        [target["target_id"] for target in paused], "reviewable": False,
                        "executable": False, "blocked_reason": "historical_exact_needs_review"})
        elif target_status.get(profile, {}).get("state") != "verified_performance":
            row.update({"target_check": "target_report_unavailable", "reviewable": False,
                        "executable": False, "blocked_reason": "target_report_unavailable"})
        else:
            row["target_check"] = "unknown_incomplete_catalog"
        result.append(row)
    return result


def summarize_rank_evidence(observations: list[dict], window: list[str]) -> dict:
    """Retain page positions as pages; they are never converted to absolute rank."""
    dates = {row.get("observed_date") for row in observations
             if row.get("state") in {"absolute_rank", "reported_position"}}
    split = (date.fromisoformat(window[0]) + timedelta(days=7)).isoformat()
    week_days = [sum(day is not None and window[0] <= day < split for day in dates),
                 sum(day is not None and split <= day <= window[1] for day in dates)]
    natural = [row for row in observations if row.get("channel") == "natural"
               and row.get("state") == "absolute_rank" and row.get("rank") is not None]
    advertising = [row for row in observations if row.get("channel") == "advertising"
                   and row.get("state") == "absolute_rank" and row.get("rank") is not None]
    ad_page = [row for row in observations if row.get("channel") == "advertising"
               and row.get("state") == "reported_position"]
    def weekly_counts(rows):
        observed = {row.get("observed_date") for row in rows}
        return [sum(day is not None and window[0] <= day < split for day in observed),
                sum(day is not None and split <= day <= window[1] for day in observed)]
    natural_week_days = weekly_counts(natural)
    advertising_week_days = weekly_counts(advertising + ad_page)
    latest_page = None
    if ad_page:
        display = str(ad_page[-1].get("display") or "")
        match = re.search(r"(?:第\s*(\d+)\s*页|\bP\s*(\d+)\b)", display, re.I)
        if match:
            latest_page = int(match.group(1) or match.group(2))
    return {"state": "verified" if all(days >= 5 for days in
                                           natural_week_days + advertising_week_days) else "insufficient_days",
            "observed_days": len(dates), "week_days": week_days,
            "natural_week_days": natural_week_days,
            "advertising_week_days": advertising_week_days, "window": window,
            "natural_latest": natural[-1]["rank"] if natural else None,
            "natural_days": len({row["observed_date"] for row in natural}),
            "advertising_latest": advertising[-1]["rank"] if advertising else None,
            "advertising_days": len({row["observed_date"] for row in advertising}),
            "advertising_page_latest": latest_page,
            "advertising_page_display": ad_page[-1].get("display") if ad_page else None,
            "attribution": "asin_external_not_target"}


def _directional_rank_days(rank: dict | None, channel: str) -> int:
    """Count real observed days without requiring a complete two-week curve."""
    if not rank:
        return 0
    weeks = rank.get(f"{channel}_week_days")
    if isinstance(weeks, list) and len(weeks) == 2:
        return sum(max(0, int(day or 0)) for day in weeks)
    days = rank.get(f"{channel}_days")
    if days is not None:
        return max(0, int(days))
    # Older verified summaries did not retain per-channel counts.
    return max(0, int(rank.get("observed_days") or 0)) if rank.get("state") == "verified" else 0


def target_bid_reviews(targets: list[dict], products: dict, group_links: dict,
                       profile_to_sid: dict[str, str], rank_by_product: dict,
                       *, negative_actions: list[dict] | None = None) -> list[dict]:
    """Show conditional bid reviews; never manufacture a numeric CPC recommendation."""
    catalog = _catalog(products, profile_to_sid)
    result = []
    for target in targets:
        if target.get("match_type") != "exact" or not target.get("target_id"):
            continue
        profile = target["profile_id"]
        affected = sorted(str(asin).upper() for asin in group_links.get((profile, target["ad_group_id"]), set()))
        parent_state = _parent_scope(profile, affected, catalog, profile_to_sid)
        if parent_state != "verified_same_parent":
            continue
        if any(target.get(field) != "enabled" for field in ("target_state", "campaign_state", "ad_group_state")):
            continue
        child_ranks = {asin: rank_by_product.get((catalog[(profile_to_sid[profile], asin)]["key"],
                                                 target["normalized_keyword"])) for asin in affected}
        def natural_signal(item):
            return (item is not None and item.get("natural_latest") is not None and
                    _directional_rank_days(item, "natural") >= 3)

        def ad_signal(item):
            return (item is not None and (item.get("advertising_latest") is not None or
                                          item.get("advertising_page_latest") is not None) and
                    _directional_rank_days(item, "advertising") >= 3)

        reference_asin = next((asin for asin, item in child_ranks.items() if ad_signal(item)), None)
        if reference_asin is None:
            reference_asin = next((asin for asin, item in child_ranks.items() if natural_signal(item)), None)
        rank = child_ranks.get(reference_asin) if reference_asin else None
        rank_ready = reference_asin is not None
        budget_ready = target.get("budget") is not None and target["budget"] > 0
        if not rank_ready or not budget_ready:
            direction = "needs_rank_and_budget" if not rank_ready and not budget_ready else (
                "needs_rank" if not rank_ready else "needs_budget")
        else:
            observed_natural = [item["natural_latest"] for item in child_ranks.values()
                                if natural_signal(item)]
            observed_ads = [item for item in child_ranks.values() if ad_signal(item)]
            weak_ad = any((item.get("advertising_latest") is not None and
                           item["advertising_latest"] > 16) or
                          (item.get("advertising_page_latest") is not None and
                           item["advertising_page_latest"] >= 2) for item in observed_ads)
            strong_ad = any((item.get("advertising_latest") is not None and
                             item["advertising_latest"] <= 16) or
                            item.get("advertising_page_latest") == 1 for item in observed_ads)
            strong_natural = any(value <= 16 for value in observed_natural)
            spend, sales = target.get("spend"), target.get("sales")
            clicks, orders = target.get("clicks") or 0, target.get("orders") or 0
            acos = spend / sales if sales and spend is not None else None
            efficient = acos is not None and acos <= .30 and orders >= 2
            waste = (clicks >= 10 and acos is not None and acos > .33) or (
                clicks >= 15 and orders == 0)
            direction = ("consider_lower" if waste else
                         "variant_rank_conflict" if weak_ad and strong_ad and efficient else
                         "consider_raise" if weak_ad and not strong_ad and not strong_natural and efficient else
                         "hold_visibility" if strong_ad and efficient else
                         "hold_organic" if strong_natural else "hold_for_review")
        campaign_spend = target.get("campaign_spend")
        budget_utilization_proxy = (campaign_spend / (target["budget"] * 14)
                                    if target.get("budget_type") in {"daily", "每日"}
                                    and budget_ready and campaign_spend is not None else None)
        adjustments = target.get("placement_adjustments") or {}
        base = target.get("base_bid")
        ceiling = (round(base * (1 + max((v for v in adjustments.values()
                                         if isinstance(v, (int, float))), default=0) / 100), 4)
                   if base is not None and base > 0 and target.get("bidding_strategy") == "legacyForSales"
                   and target.get("is_apply_time") is False else None)
        if any(action.get("kind") in {"negative", "negative_asin"} and action.get("reviewable") and
               all(action.get(field) == target.get(field) for field in
                   ("profile_id", "campaign_id", "ad_group_id", "normalized_keyword"))
               for action in (negative_actions or [])):
            direction = "conflict_negative"
        if direction in {"consider_raise", "consider_lower"} and not (base is not None and base > 0):
            direction = "needs_base_bid"
        reviewable = direction in {"consider_raise", "consider_lower"} and budget_ready
        rank_basis = ("complete_14d" if child_ranks and all(item and item.get("state") == "verified"
                                                            for item in child_ranks.values()) else "directional")
        reason = ({"consider_raise": "目标级订单与 ACOS 有效，广告位置偏后；可复核小幅提价。",
                   "consider_lower": "目标级花费效率偏弱；可复核审慎降价。"}.get(
                       direction, "精准目标竞价复核；先核对目标级表现与 SIF 词位。"))
        result.append({
            "action_key": "bid-target|" + "|".join((profile, target["campaign_id"],
                                                     target["ad_group_id"], target["target_id"])),
            "kind": "bid_review", "profile_id": profile, "sponsored_type": "sp",
            "campaign_id": target["campaign_id"], "campaign_name": target.get("campaign_name") or "",
            "ad_group_id": target["ad_group_id"], "ad_group_name": target.get("ad_group_name") or "",
            "target_id": target["target_id"], "query": target["keyword"],
            "normalized_keyword": target["normalized_keyword"], "affected_asins": affected,
            "shared_group": len(affected) > 1, "parent_scope": parent_state,
            "target_state": target["target_state"], "direction": direction,
            "reviewable": reviewable, "executable": False,
            "blocked_reason": "" if reviewable else direction,
            "budget_utilization_proxy": budget_utilization_proxy,
            "reason": reason,
            "suggested_bid": None, "effective_bid_ceiling": ceiling,
            "bid_evidence": target,
            "rank_evidence": ({**rank, "attribution": "asin_external_not_target",
                               "reference_asin": reference_asin, "review_basis": rank_basis,
                               "children": child_ranks} if rank else
                              {"state": "missing", "attribution": "asin_external_not_target",
                               "reference_asin": None, "review_basis": "missing",
                               "children": child_ranks}),
            "clicks": target.get("clicks"), "spend": target.get("spend"),
            "impressions": target.get("impressions"), "orders": target.get("orders"),
            "sales": target.get("sales"), "acos": (
                target["spend"] / target["sales"] if target.get("sales") and target.get("spend") is not None else None),
        })
    return result
