"""Attach ad-group/portfolio evidence to the current board.

Lingxing's ad_keyword_targets only covers groups with keyword targets. The
campaign-group report contains the full group list (including ASIN/product
groups) plus the portfolio. This keeps the exact-target selector inside the
same portfolio as the source action.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--board", type=Path, required=True)
    ap.add_argument("--raw", type=Path, default=None)
    args = ap.parse_args()
    board = json.loads(args.board.read_text(encoding="utf-8"))
    raw_dir = args.raw or (ROOT / "storage" / "runs" / str(board.get("run_id")) / "raw" / "lingxing")
    if not raw_dir.is_dir():
        raise SystemExit(f"raw Lingxing directory not found: {raw_dir}")
    groups: dict[tuple[str, str, str], dict] = {}
    for path in sorted(raw_dir.glob("ad_campaign_group_report-*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = ((payload.get("response") or {}).get("data") or {}).get("data") or []
        for row in rows:
            if not row.get("profile_id") or not row.get("campaign_id") or not row.get("ad_group_id"):
                continue
            key = (str(row["profile_id"]), str(row["campaign_id"]), str(row["ad_group_id"]))
            groups[key] = {
                "profile_id": key[0],
                "campaign_id": key[1],
                "campaign_name": row.get("campaign_name") or key[1],
                "ad_group_id": key[2],
                # ad_campaign_group_report exposes the human name in `name`
                # while `ad_group_name` is often null.
                "ad_group_name": row.get("ad_group_name") or row.get("name") or "未命名广告组",
                "portfolio_id": row.get("portfolio_id"),
                "portfolio_name": row.get("portfolio_name"),
                "campaign_state": row.get("campaign_state"),
                "ad_group_state": row.get("ad_group_state") or row.get("state"),
            }
    options = sorted(groups.values(), key=lambda row: (
        str(row.get("profile_id")), str(row.get("portfolio_name") or ""),
        str(row.get("campaign_name") or ""), str(row.get("ad_group_name") or "")))
    board["ad_group_options"] = options
    by_key = {(row["profile_id"], row["campaign_id"], row["ad_group_id"]): row for row in options}
    attached = 0
    action_sets = [board.get("actions") or []]
    action_sets += [product.get("actions") or [] for product in (board.get("products") or {}).values()]
    for actions in action_sets:
        for action in actions:
            key = (str(action.get("profile_id")), str(action.get("campaign_id")), str(action.get("ad_group_id")))
            group = by_key.get(key)
            if group:
                action["portfolio_id"] = group.get("portfolio_id")
                action["portfolio_name"] = group.get("portfolio_name")
                if not action.get("campaign_name") or str(action.get("campaign_name")).isdigit():
                    action["campaign_name"] = group.get("campaign_name")
                if not action.get("ad_group_name") or str(action.get("ad_group_name")).isdigit():
                    action["ad_group_name"] = group.get("ad_group_name")
                attached += 1
    for row in board.get("ad_keyword_targets") or []:
        key = (str(row.get("profile_id")), str(row.get("campaign_id")), str(row.get("ad_group_id")))
        group = by_key.get(key)
        if group:
            row["portfolio_id"] = group.get("portfolio_id")
            row["portfolio_name"] = group.get("portfolio_name")
    args.board.write_text(json.dumps(board, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(json.dumps({"groups": len(options), "actions_attached": attached,
                      "portfolios": len({row.get("portfolio_id") for row in options if row.get("portfolio_id")}),
                      "states": dict(Counter(row.get("ad_group_state") for row in options))}, ensure_ascii=False))


if __name__ == "__main__":
    main()
