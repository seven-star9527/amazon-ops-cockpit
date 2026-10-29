"""Start the selected B-line review board on an available loopback port."""

from __future__ import annotations

import argparse
import getpass
import os
import socket
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from b_ops.render import render_board
from b_ops.server import create_app
from b_ops.collect.sif import SifClient


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("run_id")
    parser.add_argument("--port", type=int, default=8767)
    parser.add_argument("--prompt-sif", action="store_true",
                        help="Prompt without echo for a temporary SIF key to enable single-ASIN refresh")
    args = parser.parse_args()
    run_dir = ROOT / "storage" / "runs" / args.run_id
    if not (run_dir / "board.json").is_file():
        raise SystemExit("B-line batch not found")
    render_board(run_dir / "board.json", run_dir / "board-ads-v7.html")
    sif_key = os.getenv("SIF_MCP_KEY") or (
        getpass.getpass("SIF MCP key (not saved): ") if args.prompt_sif else None)
    sif_client = SifClient(os.getenv("SIF_MCP_URL") or "https://mcp.sif.com/mcp", sif_key) if sif_key else None
    app = create_app(run_dir, ROOT / "storage" / "state" / "ops_state.sqlite3",
                     sif_client=sif_client, html_name="board-ads-v7.html")
    port = args.port
    while port < args.port + 50:
        with socket.socket() as sock:
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                port += 1
                continue
        break
    else:
        raise SystemExit("no available loopback port")
    print(f"Local review board: http://127.0.0.1:{port}/", flush=True)
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
