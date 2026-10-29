"""Execute a frozen ad write batch item-by-item.

The batch never stops because one item is blocked or fails. Each item is
reported as succeeded / already_exists / failed / unknown / blocked. There is
still no retry: unknown means "do not retry this item automatically".
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from b_ops.collect.lingxing import LingxingClient

ALLOWED = {"negative_keyword", "negative_asin", "exact_keyword", "exact_product", "bid"}


def _digest(items: list[dict]) -> str:
    return hashlib.sha256(json.dumps(items, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def _item_error(item: dict) -> str | None:
    if item.get("write_type") not in ALLOWED:
        return f"未知写入类型: {item.get('write_type')}"
    if not item.get("profile_id"):
        return "缺少 Profile"
    if item.get("write_type") in {"negative_keyword", "negative_asin"}:
        if not item.get("campaign_id") or not item.get("ad_group_id"):
            return "否词缺少 Campaign/Ad Group"
    if item.get("write_type") in {"exact_keyword", "exact_product"}:
        if not item.get("target_campaign_id") or not item.get("target_ad_group_id"):
            return "精准缺少承接组"
        if not item.get("bid"):
            return "精准缺少出价"
    if item.get("write_type") == "bid":
        if not item.get("target_id") or not item.get("bid"):
            return "调价缺少 Target/Bid"
    return None


def split_items(batch: dict) -> tuple[list[dict], list[dict]]:
    valid, blocked = [], []
    for item in batch.get("items") or []:
        reason = _item_error(item)
        if reason:
            blocked.append({"action_key": item.get("action_key"), "write_type": item.get("write_type"),
                            "reason": reason})
        else:
            valid.append(item)
    for item in batch.get("blocked") or []:
        blocked.append({"action_key": item.get("action_key"), "write_type": item.get("write_type"),
                        "reason": item.get("reason") or "批次生成时已阻止"})
    return valid, blocked


def preflight(batch: dict, board: dict) -> list[str]:
    """Only hard batch-level errors. Item errors are isolated, never global."""
    errors = []
    items = batch.get("items") or []
    if batch.get("schema") != "amazon-ops-b/ad-write-batch/1":
        errors.append("批次 schema 无效")
    if not batch.get("batch_id") or not batch.get("content_sha256"):
        errors.append("批次缺少 ID 或摘要")
    if _digest(items) != batch.get("content_sha256"):
        errors.append("批次内容与摘要不一致")
    try:
        datetime.fromisoformat(batch["created_at"])
    except Exception:
        errors.append("批次时间无效")
    return errors


def _already_exists(response) -> bool:
    text = json.dumps(response, ensure_ascii=False).lower()
    return "already_exists" in text or "已存在" in text or "duplicate" in text


def execute(batch: dict, confirmation: str, *, dry_run: bool = True) -> dict:
    items, blocked = split_items(batch)
    expected = f"{batch.get('batch_id')}:{batch.get('content_sha256')}"
    if confirmation != expected:
        raise SystemExit("confirmation must exactly match batch_id:content_sha256")
    if dry_run:
        return {"status": "preflight_only", "expected_confirmation": expected,
                "items": len(items), "blocked": blocked}
    key = os.getenv("LINGXING_MCP_KEY")
    if not key:
        raise SystemExit("LINGXING_MCP_KEY is required for execution")
    client = LingxingClient(os.getenv("LINGXING_MCP_URL") or "https://openmcp.lingxing.com/mcp-servers/lingxing-mcp", key)
    results = []
    for item in items:
        record = {"action_key": item.get("action_key"), "write_type": item.get("write_type"),
                  "tool": item.get("tool"), "status": "pending"}
        try:
            response = client.write(item["tool"], item["params"])
            record["status"] = "already_exists" if _already_exists(response) else "succeeded"
            record["response"] = response
        except Exception as exc:
            text = str(exc)
            if "已存在" in text or "duplicate" in text.lower():
                record["status"] = "already_exists"
            elif 'business failure' in text.lower():
                record["status"] = "failed"
            else:
                record["status"] = "unknown"
            record["error_type"] = type(exc).__name__
            record["error"] = text[:300]
            # Continue with the remaining items; never retry this one automatically.
        results.append(record)
    return {"status": "executed", "batch_id": batch.get("batch_id"),
            "confirmation": expected, "items": len(items), "blocked": blocked,
            "summary": {status: sum(1 for row in results if row["status"] == status)
                        for status in ("succeeded", "already_exists", "failed", "unknown")},
            "results": results}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("batch", type=Path)
    ap.add_argument("--board", type=Path, required=True)
    ap.add_argument("--confirm", default="")
    ap.add_argument("--preflight-only", action="store_true")
    ap.add_argument("--execute", action="store_true")
    args = ap.parse_args()
    batch = json.loads(args.batch.read_text(encoding="utf-8"))
    board = json.loads(args.board.read_text(encoding="utf-8"))
    errors = preflight(batch, board)
    if errors:
        print(json.dumps({"status": "blocked", "errors": errors}, ensure_ascii=False))
        raise SystemExit(1)
    valid, blocked = split_items(batch)
    if args.preflight_only:
        print(json.dumps({"status": "ok", "expected_confirmation": f"{batch['batch_id']}:{batch['content_sha256']}",
                          "executable": len(valid), "blocked": blocked,
                          "summary": batch.get("summary")}, ensure_ascii=False))
        return
    if not args.execute:
        raise SystemExit("use --preflight-only or --execute --confirm batch_id:digest")
    out = args.batch.with_name(args.batch.stem + "-receipt.json")
    if out.exists():
        raise SystemExit(f"receipt already exists: {out}; refusing a possible duplicate write")
    if not valid:
        result = {"status": "no_items", "batch_id": batch.get("batch_id"),
                  "confirmation": f"{batch.get('batch_id')}:{batch.get('content_sha256')}",
                  "blocked": blocked, "results": []}
    else:
        result = execute(batch, args.confirm, dry_run=False)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
