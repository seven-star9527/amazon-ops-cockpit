"""Canonical Amazon metric grain, provenance and cautious derivations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta


LABELS = {
    "sessions_total": "总点击",
    "ad_clicks": "广告点击",
    "natural_sessions_est": "自然点击（估算）",
    "units": "销量",
    "sales": "销售额",
    "ad_spend": "广告花费",
    "ad_sales": "广告归因销售额",
}


@dataclass(frozen=True)
class Metric:
    name: str
    scope: str
    period_start: str
    period_end: str
    unit: str
    value: float | None
    quality: str
    source_ref: str
    formula: str = ""

    @property
    def label(self) -> str:
        return LABELS.get(self.name, self.name)


def aligned_natural_sessions(total: Metric, ads: Metric) -> Metric:
    formula = "总点击 - 广告点击；相同产品、站点与期间，仅作运营估算"
    result = Metric("natural_sessions_est", total.scope, total.period_start, total.period_end,
                    "count", None, "missing", f"{total.source_ref}|{ads.source_ref}", formula)
    if (total.scope, total.period_start, total.period_end, total.unit) != (
            ads.scope, ads.period_start, ads.period_end, ads.unit):
        return result
    if total.quality not in {"measured", "zero"} or ads.quality not in {"measured", "zero"}:
        return result
    if total.value is None or ads.value is None:
        return result
    if ads.value > total.value or min(total.value, ads.value) < 0:
        return Metric(**{**result.__dict__, "quality": "conflicting"})
    return Metric(**{**result.__dict__, "value": total.value - ads.value, "quality": "derived"})


def aggregate_ratio(pairs: list[tuple[float, float]]) -> float | None:
    numerator = sum(row[0] for row in pairs)
    denominator = sum(row[1] for row in pairs)
    return numerator / denominator if denominator > 0 else None


def iso_weeks(today: str | date, *, count: int = 8) -> list[dict[str, str]]:
    current = date.fromisoformat(today) if isinstance(today, str) else today
    this_monday = current - timedelta(days=current.weekday())
    output = []
    for offset in range(count, 0, -1):
        monday = this_monday - timedelta(weeks=offset)
        output.append({"label": f"W{monday.isocalendar().week:02d}",
                       "iso_year": str(monday.isocalendar().year),
                       "start": monday.isoformat(),
                       "end": (monday + timedelta(days=6)).isoformat()})
    return output
