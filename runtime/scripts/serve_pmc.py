"""Serve the current PMC board with the review token enabled.

The standalone HTML is intentionally read-only. This command creates a small
review run around the same board, so the panel buttons can persist decisions
and the agent can build a write batch.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import socket
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from b_ops.render import render_board
from b_ops.server import create_app


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--board", type=Path, default=ROOT / "storage/pmc_sources/2026-10-22/board-pmc.json")
    ap.add_argument("--state", type=Path, default=ROOT / "storage/state/ops_state.sqlite3")
    ap.add_argument("--port", type=int, default=8768)
    args = ap.parse_args()
    board = json.loads(args.board.read_text(encoding="utf-8"))
    run_id = str(board["run_id"])
    review_dir = ROOT / "storage/review_runs" / run_id
    review_dir.mkdir(parents=True, exist_ok=True)
    board_bytes = json.dumps(board, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    (review_dir / "board.json").write_bytes(board_bytes)
    (review_dir / "manifest.json").write_text(json.dumps({
        "state": "complete", "run_id": run_id,
        "batch_sha256": hashlib.sha256(board_bytes).hexdigest(),
    }), encoding="utf-8")
    render_board(review_dir / "board.json", review_dir / "board-ads-v7.html")
    app = create_app(review_dir, args.state, html_name="board-ads-v7.html")
    port = args.port
    while port < args.port + 50:
        with socket.socket() as sock:
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                port += 1
                continue
        break
    print(f"Interactive board: http://127.0.0.1:{port}/", flush=True)
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
