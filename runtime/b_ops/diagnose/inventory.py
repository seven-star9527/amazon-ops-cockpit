"""Inventory checks using SKU-summed sellable stock and completed-week demand."""

from __future__ import annotations

from b_ops.model.snapshot import number
from b_ops.model.sales_pace import sales_pace


def inventory_issues(product: dict) -> list[dict]:
    pace = product.get("sales_pace") or sales_pace(product)
    stock = product.get("stock") or {}
    sellable = number(stock.get("sellable"))
    age = number(stock.get("age_181_plus"))
    excess = number(stock.get("excess_estimate"))
    age_issues = []
    if (age is not None and age >= 30) or (excess is not None and excess >= 20):
        age_issues.append({"domain": "inventory", "type": "aged_excess", "severity": "medium",
                           "title": "长龄 / 冗余库存需复核",
                           "hypothesis": "领星 FBA 库龄或预估冗余已达到复核门槛；具体清货方式需结合费用和利润权限判断",
                           "evidence": {"age_181_plus": age, "excess_estimate": excess,
                                        "storage_cost_next_month": stock.get("storage_cost_next_month")},
                           "gaps": [], "suggested_quantity": None, "actionability": 1,
                           "next_step": "核对库龄分布、仓储成本与价格/促销可行性"})
    if pace.get("quality") != "measured" or pace.get("actual_daily_units_28d") is None:
        return age_issues + [{"domain": "inventory", "type": "demand_gap", "severity": "gap", "title": "销量周数据不完整，暂不估算补货量",
                 "hypothesis": "缺少连续自然周的可靠需求", "evidence": {"sellable": sellable}, "gaps": ["4 个完整自然周销量"],
                 "suggested_quantity": None, "actionability": 0}]
    daily = pace["actual_daily_units_28d"]
    if daily <= 0:
        return age_issues
    if sellable is None:
        return age_issues + [{"domain": "inventory", "type": "stock_gap", "severity": "gap", "title": "FBA 可售数量缺失",
                 "hypothesis": "不可计算可售天数", "evidence": {"daily_units": daily}, "gaps": ["FBA 可售数量"],
                 "suggested_quantity": None, "actionability": 0}]
    cover = sellable / daily
    issue_type, severity, title = None, None, None
    if sellable <= 0:
        issue_type, severity, title = "stockout", "critical", "FBA 可售库存为 0"
    elif cover < 14:
        issue_type, severity, title = "low_cover", "high", "可售库存不足两周"
    elif cover > 180:
        issue_type, severity, title = "excess_cover", "medium", "可售库存覆盖超过 180 天"
    if issue_type is None:
        return age_issues
    gaps = ["ETA", "采购/入仓周期"] if cover < 14 else ["库龄和仓储费"]
    return age_issues + [{"domain": "inventory", "type": issue_type, "severity": severity, "title": title,
             "hypothesis": "按近 4 个完整自然周销量估算；缺货期间的销量可能低估需求",
             "evidence": {"sellable": sellable, "inbound_shipped": stock.get("inbound_shipped"),
                          "daily_units": round(daily, 3), "days_cover": round(cover, 1),
                          "weeks": pace.get("source_weeks", [])},
             "gaps": gaps, "suggested_quantity": None, "actionability": 1,
             "next_step": "核对在途货件 ETA 和采购周期，再确认发货日期与数量" if cover < 14 else "核对库龄、费用与促销清货空间"}]
