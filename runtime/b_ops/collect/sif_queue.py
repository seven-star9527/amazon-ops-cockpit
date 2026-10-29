"""Bounded SIF ASIN queue using the canonical actual sales pace."""

from __future__ import annotations

from collections import defaultdict

from b_ops.collect.replay import ReplayMissing


class SifRunBudget:
    """Keep signal failures separate from the quota for actual rank attempts."""

    def __init__(self, *, rank_limit: int = 25, failure_limit: int = 3):
        self.rank_limit = max(0, int(rank_limit))
        self.failure_limit = max(1, int(failure_limit))
        self.rank_attempts = 0
        self.consecutive_live_failures = 0

    def can_query_signal(self) -> bool:
        return self.consecutive_live_failures < self.failure_limit

    def record_signal_error(self, exc: Exception) -> str:
        if isinstance(exc, ReplayMissing):
            return "replay_missing"
        self.consecutive_live_failures += 1
        return "source_failed"

    def record_signal_success(self) -> None:
        self.consecutive_live_failures = 0

    def reserve_rank(self) -> bool:
        if self.rank_attempts >= self.rank_limit:
            return False
        self.rank_attempts += 1
        return True


def keyword_batches(terms: list[str], *, size: int = 10) -> list[list[str]]:
    if size <= 0:
        raise ValueError("keyword batch size must be positive")
    return [terms[index:index + size] for index in range(0, len(terms), size)]


def build_sif_queue(products: list[dict], *, manual_priority: set[str] | None = None,
                    limit: int = 25, last_success: dict | None = None) -> dict:
    manual_priority = manual_priority or set()
    last_success = last_success or {}
    grouped = defaultdict(list)
    for product in products:
        if str(product.get("status")) == "1":
            grouped[(product["site"], product["asin"])].append(product)
    entries = []
    deferred = {}
    for (site, asin), members in grouped.items():
        paces = [member.get("sales_pace") or {} for member in members]
        manual = any(member["key"] in manual_priority for member in members)
        four_week = max((pace.get("units_28d") for pace in paces if pace.get("units_28d") is not None), default=None)
        recent = max((pace.get("latest_week_units") for pace in paces if pace.get("latest_week_units") is not None), default=None)
        lane = "operator_priority" if manual else "stable" if four_week is not None and four_week >= 56 else \
            "recent_growth" if recent is not None and recent >= 14 else None
        if lane is None:
            reason = "below_sales_threshold" if four_week is not None else "sales_data_gap"
            deferred.update({member["key"]: reason for member in members})
            continue
        entries.append({"site": site, "asin": asin, "products": members, "lane": lane,
                        "reason": {"operator_priority": "运营指定", "stable": "近四周实际日均≥2件",
                                   "recent_growth": "最近完整周销量≥14件"}[lane],
                        "units_28d": four_week, "latest_week_units": recent,
                        "last_success": last_success.get((site, asin)) or ""})
    ranked = sorted(entries, key=lambda item: (
        {"operator_priority": 0, "stable": 1, "recent_growth": 2}[item["lane"]],
        -(item["units_28d"] or 0) if item["lane"] == "stable" else -(item["latest_week_units"] or 0),
        item["last_success"], item["asin"],
    ))
    limit = max(int(limit), 0)
    if limit and any(item["lane"] == "recent_growth" for item in ranked):
        growth_slots = min(max(1, limit // 5), sum(item["lane"] == "recent_growth" for item in ranked))
        chosen = ranked[:limit]
        if not any(item["lane"] == "recent_growth" for item in chosen):
            extras = [item for item in ranked[limit:] if item["lane"] == "recent_growth"][:growth_slots]
            chosen = chosen[:max(0, limit - len(extras))] + extras
    else:
        chosen = ranked[:limit]
    chosen_ids = {(item["site"], item["asin"]) for item in chosen}
    for item in ranked:
        if (item["site"], item["asin"]) not in chosen_ids:
            deferred.update({member["key"]: "sif_call_budget" for member in item["products"]})
    return {"selected": chosen, "deferred": deferred, "eligible": len(ranked),
            "active": sum(len(members) for members in grouped.values())}
