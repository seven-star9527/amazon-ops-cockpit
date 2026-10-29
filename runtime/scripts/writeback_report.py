"""Render a human-readable writeback report from a frozen batch and receipt."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]


def _index(board: dict):
    actions, products = {}, {}
    for product in (board.get("products") or {}).values():
        meta = {"name": product.get("name"), "asin": product.get("asin")}
        for action in product.get("actions") or []:
            if action.get("action_key"):
                actions[str(action["action_key"])] = action
                products[str(action["action_key"])] = meta
    for action in board.get("actions") or []:
        if action.get("action_key"):
            actions.setdefault(str(action["action_key"]), action)
    return actions, products


def _target_id(value):
    if isinstance(value, dict):
        if value.get("targetId"):
            return value["targetId"]
        for child in value.values():
            found = _target_id(child)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _target_id(child)
            if found:
                return found
    return None


def _trace_id(value):
    if isinstance(value, dict):
        if value.get("traceId"):
            return value["traceId"]
        for child in value.values():
            found = _trace_id(child)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _trace_id(child)
            if found:
                return found
    return None


def _label(item: dict) -> str:
    return {
        "bid": "调价",
        "exact_keyword": "新增精准关键词",
        "exact_product": "新增商品精准投放",
        "negative_keyword": "新增否定关键词",
        "negative_asin": "新增否定 ASIN",
    }.get(item.get("write_type"), item.get("write_type") or "写回")


def _status(value: str) -> str:
    return {"succeeded": "成功", "already_exists": "已存在", "failed": "失败", "unknown": "结果未知"}.get(value, value or "未知")


def _target_names(board: dict, item: dict):
    campaign = item.get("target_campaign_id")
    group = item.get("target_ad_group_id")
    if not campaign or not group:
        return None, None
    row = next((row for row in board.get("ad_group_options") or []
                if str(row.get("campaign_id")) == str(campaign)
                and str(row.get("ad_group_id")) == str(group)), None)
    return (row.get("campaign_name"), row.get("ad_group_name")) if row else (None, None)


def render(board: dict, batch: dict, receipt: dict) -> str:
    actions, products = _index(board)
    results = {row.get("action_key"): row for row in receipt.get("results") or []}
    counts = Counter(_status(row.get("status")) for row in receipt.get("results") or [])
    blocked = receipt.get("blocked") or []
    lines = ["# 广告写回报告", "",
             f"- 批次：{batch.get('batch_id')}",
             f"- 时间：{(datetime.fromisoformat(batch['created_at']).astimezone(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M') if batch.get('created_at') else '未记录')}",
             f"- 结果：成功 {counts.get('成功', 0)} / 已存在 {counts.get('已存在', 0)} / 失败 {counts.get('失败', 0)} / 未知 {counts.get('未知', 0)} / 未执行 {len(blocked)}",
             ""]
    for index, item in enumerate(batch.get("items") or [], start=1):
        action = actions.get(item.get("action_key"), {})
        product = products.get(item.get("action_key"), {})
        result = results.get(item.get("action_key"), {})
        status = result.get("status") or "missing"
        target_campaign, target_group = _target_names(board, item)
        campaign = target_campaign or item.get("target_campaign_name") or item.get("campaign_name") or action.get("campaign_name") or "未解析"
        group = target_group or item.get("target_ad_group_name") or item.get("ad_group_name") or action.get("ad_group_name") or "未解析"
        portfolio = item.get("portfolio_name") or action.get("portfolio_name") or "未解析"
        product_name = item.get("product_name") or product.get("name") or "未解析"
        asin = item.get("asin") or product.get("asin") or "未解析"
        lines += [f"## {index}. {_label(item)}", "",
                  f"- 产品：{product_name}（{asin}）",
                  f"- 广告组合：{portfolio}",
                  f"- 活动：{campaign}",
                  f"- 广告组：{group}",
                  f"- 对象：{item.get('query') or action.get('query') or '未解析'}"]
        if item.get("write_type") == "bid":
            old = item.get("old_bid")
            if old is None:
                old = (action.get("bid_evidence") or {}).get("base_bid")
            lines += [f"- 原价：{'' if old is None else f'£{float(old):.2f}'}",
                      f"- 现价：£{float(item.get('bid')):.2f}"]
        elif item.get("write_type") in {"exact_keyword", "exact_product"}:
            lines += [f"- 方式：{'商品精准' if item.get('write_type') == 'exact_product' else '关键词精准'}",
                      f"- 出价：£{float(item.get('bid')):.2f}"]
        else:
            lines += [f"- 方式：{item.get('match_type') or '否定'}"]
        lines += [f"- 结果：{_status(status)}", ""]
        tech = {"targetId": _target_id(result.get("response")), "traceId": _trace_id(result.get("response"))}
        lines += ["<details><summary>技术详情</summary>", "",
                  f"- targetId：{tech['targetId'] or '未返回'}",
                  f"- traceId：{tech['traceId'] or '未返回'}",
                  f"- action_key：{item.get('action_key')}", "", "</details>", ""]
    if blocked:
        lines += ["## 未执行项", ""]
        for item in blocked:
            lines += [f"- {item.get('action_key') or '未命名动作'}：{item.get('reason') or '已阻止'}"]
        lines += [""]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--board", type=Path, required=True)
    ap.add_argument("--batch", type=Path, required=True)
    ap.add_argument("--receipt", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    report = render(json.loads(args.board.read_text(encoding="utf-8")),
                    json.loads(args.batch.read_text(encoding="utf-8")),
                    json.loads(args.receipt.read_text(encoding="utf-8")))
    args.out.write_text(report, encoding="utf-8")
    print(str(args.out))


if __name__ == "__main__":
    main()
