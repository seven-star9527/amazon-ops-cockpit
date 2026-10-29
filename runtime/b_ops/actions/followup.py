"""Comparison labels for later runs; observations are not causal effect claims."""

from __future__ import annotations

from b_ops.model.snapshot import number


def assess_followup(action: dict, after_rows: list[dict], *, days_elapsed: int,
                    confounders: list[str] | None = None) -> dict:
    if days_elapsed < 7:
        return {"state": "not_due", "message": "第 7 天复核尚未到期"}
    relevant = [row for row in after_rows
                if str(row.get("profile_id")) == str(action.get("profile_id"))
                and str(row.get("ad_group_id")) == str(action.get("ad_group_id"))
                and str(row.get("query", "")).casefold() == str(action.get("query", "")).casefold()]
    if not relevant:
        return {"state": "source_missing", "message": "未取得同范围后续搜索词，不能推断效果"}
    before = action.get("before") or {}
    old_spend = number(before.get("spend"))
    new_spend = sum(number(row.get("spend")) or 0 for row in relevant)
    if old_spend is None:
        return {"state": "source_missing", "message": "缺少执行前同口径花费"}
    if confounders:
        return {"state": "confounded", "message": "同期还有其他变化；只展示观察值，不归因",
                "confounders": confounders, "before_spend": old_spend, "after_spend": new_spend}
    changed = abs(new_spend - old_spend) > .01
    return {"state": "observed_change" if changed else "no_change",
            "message": "执行后观察到花费变化；变化可能受其他因素影响" if changed else "同范围花费暂未见明显变化",
            "before_spend": old_spend, "after_spend": new_spend}
