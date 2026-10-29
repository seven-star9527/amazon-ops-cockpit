"""One source-backed actual sales pace for an ASIN's completed ISO weeks."""

from __future__ import annotations

from b_ops.model.snapshot import number


def sales_pace(product: dict) -> dict:
    weeks = list(product.get("weeks") or [])[-4:]
    latest = weeks[-1] if weeks else None
    latest_units = number(latest.get("units")) if latest and latest.get("quality") == "measured" else None
    measured = len(weeks) == 4 and all(
        week.get("quality") == "measured" and number(week.get("units")) is not None
        for week in weeks
    )
    units = sum(number(week["units"]) for week in weeks) if measured else None
    return {
        "units_28d": units,
        "actual_daily_units_28d": units / 28 if units is not None else None,
        "latest_week_units": latest_units,
        "quality": "measured" if measured else "partial" if latest_units is not None else "missing",
        "source_weeks": [week.get("start") or week.get("label") for week in weeks],
    }
