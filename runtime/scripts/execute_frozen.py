"""Write a reviewed frozen SP batch only with fresh remote preflight and exact confirmation."""

from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from b_ops.actions.batch import canonical_hash
from b_ops.actions.execute import LingxingWriteAdapter, execute_batch
from b_ops.actions.preflight import validate_preflight
from b_ops.model.storage import StateStore


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("run_id")
    parser.add_argument("batch_id")
    parser.add_argument("--preflight", type=Path, required=True)
    parser.add_argument("--confirm", required=True, help="Exact batch_id:digest from frozen preview")
    args = parser.parse_args()
    if not args.run_id.startswith("b-") or any(ch in args.run_id for ch in ("/", "\\", ".")):
        raise SystemExit("invalid B-line run ID")
    if not args.batch_id.startswith(args.run_id + "-") or any(ch in args.batch_id for ch in ("/", "\\", ".")):
        raise SystemExit("invalid frozen batch ID")
    run = ROOT / "storage" / "runs" / args.run_id
    board_bytes = (run / "board.json").read_bytes()
    manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    batch = json.loads((run / "actions" / f"{args.batch_id}.json").read_text(encoding="utf-8"))
    if manifest.get("state") != "complete" or hashlib.sha256(board_bytes).hexdigest() != manifest.get("batch_sha256"):
        raise SystemExit("source run hash/state mismatch")
    if batch.get("source_sha256") != manifest["batch_sha256"]:
        raise SystemExit("frozen batch source changed")
    latest = StateStore(ROOT / "storage" / "state" / "ops_state.sqlite3").decision_version(args.run_id)
    if latest != batch.get("decision_version"):
        raise SystemExit("operator decisions changed; refreeze after agent review")
    core = {name: value for name, value in batch.items() if name not in {"batch_id", "content_sha256"}}
    if canonical_hash(core) != batch.get("content_sha256"):
        raise SystemExit("frozen digest mismatch")
    if args.confirm != f"{batch['batch_id']}:{batch['content_sha256']}":
        raise SystemExit("exact batch ID and digest confirmation required")
    check = json.loads(args.preflight.read_text(encoding="utf-8"))
    validate_preflight(batch, check)
    receipt_path = run / "actions" / f"{args.batch_id}.receipt.json"
    intent_path = run / "actions" / f"{args.batch_id}.intent.json"
    if receipt_path.exists() or intent_path.exists():
        raise SystemExit("batch submission already started; inspect receipt/read-back before any new attempt")
    key = os.getenv("LINGXING_MCP_KEY") or getpass.getpass("Lingxing MCP key: ")
    writer = LingxingWriteAdapter(os.getenv("LINGXING_MCP_URL") or "https://openmcp.lingxing.com/mcp-servers/lingxing-mcp", key)
    del key
    with intent_path.open("x", encoding="utf-8") as journal:
        journal.write(json.dumps({"batch_id": batch["batch_id"], "content_sha256": batch["content_sha256"],
                                  "state": "submission_started_no_automatic_retry"}, ensure_ascii=False) + "\n")
        journal.flush()
        os.fsync(journal.fileno())
    receipt = execute_batch(batch, args.confirm, writer)
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"receipt": str(receipt_path), "statuses": [row["status"] for row in receipt["items"]],
                      "note": "accepted only means API acceptance; run a separate read-back"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
