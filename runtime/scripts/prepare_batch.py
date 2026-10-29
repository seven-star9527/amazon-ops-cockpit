"""Freeze only current operator-accepted items approved in a Codex review JSON."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from b_ops.actions.batch import build_batch
from b_ops.model.storage import StateStore


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("run_id")
    parser.add_argument("--profile", required=True)
    parser.add_argument("--review", type=Path, required=True,
                        help="Codex review JSON with exact run/hash/version and approved action keys")
    args = parser.parse_args()
    if not args.run_id.startswith("b-") or any(ch in args.run_id for ch in ("/", "\\", ".")):
        raise SystemExit("invalid B-line run ID")
    run = ROOT / "storage" / "runs" / args.run_id
    board_bytes = (run / "board.json").read_bytes()
    board = json.loads(board_bytes)
    manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("state") != "complete" or manifest.get("run_id") != args.run_id:
        raise SystemExit("run is not complete")
    if hashlib.sha256(board_bytes).hexdigest() != manifest.get("batch_sha256"):
        raise SystemExit("board hash mismatch")
    review = json.loads(args.review.read_text(encoding="utf-8"))
    state = StateStore(ROOT / "storage" / "state" / "ops_state.sqlite3")
    frozen = build_batch(board, state.latest_decisions(args.run_id), review, args.profile, manifest=manifest)
    destination = run / "actions" / f"{frozen['batch_id']}.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise SystemExit("frozen batch already exists; do not overwrite")
    destination.write_text(json.dumps(frozen, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"path": str(destination), "batch_id": frozen["batch_id"],
                      "digest": frozen["content_sha256"], "items": len(frozen["items"]),
                      "remote_write": False}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
