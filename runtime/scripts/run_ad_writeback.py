"""One-command, best-effort ad writeback workflow.

Preview:
  python scripts/run_ad_writeback.py --board ... --state ... --preview

Execute saved decisions (panel save is the authorization):
  python scripts/run_ad_writeback.py --board ... --state ... --execute-saved

High-risk/manual hash confirmation:
  python scripts/run_ad_writeback.py --board ... --state ... \
    --execute --confirm "<batch_id>:<content_sha256>"

One item failing/blocking/unknown never stops the remaining items.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from b_ops.model.storage import StateStore
from prepare_ad_write_batch import build
from execute_ad_write_batch import execute, preflight, split_items
from writeback_report import render


def _paths(board: Path, out_dir: Path | None):
    target = out_dir or (board.parent / "writeback")
    target.mkdir(parents=True, exist_ok=True)
    return target, target / "ad-write-batch.json"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--board", type=Path, required=True)
    ap.add_argument("--state", type=Path, required=True)
    ap.add_argument("--out-dir", type=Path, default=None)
    ap.add_argument("--preview", action="store_true")
    ap.add_argument("--execute", action="store_true")
    ap.add_argument("--execute-saved", action="store_true",
                    help="Execute the current panel decisions without a second hash confirmation; the panel save is the authorization.")
    ap.add_argument("--confirm", default="")
    args = ap.parse_args()
    board = json.loads(args.board.read_text(encoding="utf-8"))
    out_dir, batch_path = _paths(args.board, args.out_dir)
    state = StateStore(args.state)
    rebuild = args.preview or args.execute_saved or not batch_path.exists()
    if rebuild:
        batch = build(board, state.latest_decisions(board["run_id"]))
        batch_path.write_text(json.dumps(batch, ensure_ascii=False, indent=2), encoding="utf-8")
        if args.preview:
            valid, blocked = split_items(batch)
            print(json.dumps({"status": "preview", "batch_id": batch["batch_id"],
                              "digest": batch["content_sha256"], "executable": len(valid),
                              "blocked": blocked, "summary": batch.get("summary"),
                              "batch_path": str(batch_path)}, ensure_ascii=False))
            return
    batch = json.loads(batch_path.read_text(encoding="utf-8"))
    errors = preflight(batch, board)
    if errors:
        print(json.dumps({"status": "blocked", "errors": errors}, ensure_ascii=False))
        raise SystemExit(1)
    if not args.execute and not args.execute_saved:
        raise SystemExit("use --preview, --execute-saved, or --execute --confirm batch_id:digest")
    receipt_path = out_dir / f"ad-write-batch-{batch.get('batch_id')}-receipt.json"
    report_path = out_dir / "ad-writeback-report.md"
    if receipt_path.exists():
        raise SystemExit(f"receipt already exists: {receipt_path}")
    valid, blocked = split_items(batch)
    confirmation = f"{batch.get('batch_id')}:{batch.get('content_sha256')}"
    if not valid:
        receipt = {"status": "no_items", "batch_id": batch.get("batch_id"),
                   "confirmation": confirmation, "blocked": blocked, "results": []}
    else:
        # Panel save is the operator authorization. --execute (with an explicit
        # hash) remains available for high-risk/manual runs.
        receipt = execute(batch, confirmation if args.execute_saved else args.confirm, dry_run=False)
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    report = render(board, batch, receipt)
    report_path.write_text(report, encoding="utf-8")
    executed_keys = [row.get("action_key") for row in receipt.get("results") or []
                     if row.get("status") in {"succeeded", "already_exists"}]
    if executed_keys:
        state.mark_executed(board["run_id"], executed_keys, batch["batch_id"])
    print(json.dumps({"status": receipt.get("status"), "batch_id": batch.get("batch_id"),
                      "executable": len(valid), "blocked": blocked,
                      "summary": receipt.get("summary") or {},
                      "receipt": str(receipt_path), "report": str(report_path)},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
