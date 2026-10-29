#!/usr/bin/env python3
"""Launch the complete Amazon operations cockpit, never the legacy negative-only dashboard."""

from __future__ import annotations

import argparse
import os
import json
import importlib.metadata
import shutil
import subprocess
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "runtime"))
from b_ops.paths import data_root
BOARD_GLOBS = (
    "storage/pmc_sources/*/board-pmc.json",
    "board-pmc.json",
    "inventory/board-pmc.json",
)


def find_runtime() -> Path:
    candidates = []
    env = os.getenv("AMAZON_OPS_RUNTIME")
    if env:
        candidates.append(Path(env))
    candidates.extend((
        SKILL_ROOT / "runtime",
        SKILL_ROOT.parent / "amazon-ops-b-runtime",
        Path.cwd() / "amazon-ops-b-runtime",
    ))
    for candidate in candidates:
        if (candidate / "scripts" / "serve_pmc.py").is_file():
            return candidate.resolve()
    raise SystemExit(
        "找不到 amazon-ops-b-runtime。请设置 AMAZON_OPS_RUNTIME，"
        "或把 runtime 目录放在 skill 的 runtime/ 下。"
    )


def find_board(runtime: Path) -> Path | None:
    paths = []
    for pattern in BOARD_GLOBS:
        paths.extend(runtime.glob(pattern))
    if not paths:
        return None
    return max(paths, key=lambda p: p.stat().st_mtime)


def check(runtime: Path, root: Path, board=None) -> int:
    board = board or find_board(root)
    state = root / "storage" / "state" / "ops_state.sqlite3"
    print(f"runtime={runtime}")
    print(f"python={sys.version.split()[0]}")
    print(f"node={shutil.which('node') or 'missing'}")
    print(f"serve_pmc={(runtime / 'scripts' / 'serve_pmc.py').is_file()}")
    print(f"board={board or 'MISSING'}")
    print(f"state={state if state.is_file() else 'MISSING'}")
    print(f"legacy_dashboard={(SKILL_ROOT / 'scripts' / 'dashboard_server.py').is_file()}")
    if board is None:
        print("STATUS=NO_FULL_BOARD")
        print("说明：没有完整看板数据；不会启动否词单页。先按 references/full-cockpit.md 生成 board-pmc.json。")
        return 2
    try:
        doc = json.loads(board.read_text(encoding="utf-8"))
        if not isinstance(doc, dict) or not str(doc.get("run_id", "")).startswith("b-") or not isinstance(doc.get("products"), dict) or not doc.get("inventory_batch"):
            raise ValueError("invalid board schema")
        if not shutil.which("node"):
            raise ValueError("Node is required for inventory calculations")
        if sys.prefix == sys.base_prefix:
            raise ValueError("use the isolated venv; run scripts/bootstrap.py")
        for line in (runtime / "requirements-runtime.txt").read_text().splitlines():
            if "==" in line:
                name, version = line.split("==")
                if importlib.metadata.version(name) != version:
                    raise ValueError(f"dependency mismatch: {name}")
        print(f"run_id={doc['run_id']}; source dates remain those of the snapshot")
        print(f"data_dir={root}")
    except (OSError, ValueError, importlib.metadata.PackageNotFoundError) as exc:
        print(f"STATUS=NOT_READY: {exc}")
        return 2
    print("STATUS=READY_READ_ONLY")
    return 0


def serve(runtime: Path, board: Path | None, state: Path | None, port: int, root: Path) -> int:
    board = board or find_board(root)
    if board is None:
        print("拒绝启动：没有完整看板 board-pmc.json。", file=sys.stderr)
        print("不会用旧 dashboard_server.py 冒充完整看板。", file=sys.stderr)
        print("先按 references/full-cockpit.md 生成完整看板。", file=sys.stderr)
        return 2
    if not board.is_file():
        print(f"board 不存在：{board}", file=sys.stderr)
        return 2
    if check(runtime, root, board):
        return 2
    from b_ops.render import render_board
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    output = root / "web" / "index.html"
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".tmp.html")
    render_board(board, temporary)
    temporary.replace(output)
    class ReadOnlyHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path not in ('/', '/index.html'):
                self.send_error(404)
                return
            body = output.read_bytes()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
    server = ThreadingHTTPServer(('127.0.0.1', port), ReadOnlyHandler)
    print(f"Read-only cockpit: http://127.0.0.1:{server.server_port}/", flush=True)
    server.serve_forever()
    return 0



def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--board", type=Path)
    parser.add_argument("--state", type=Path)
    parser.add_argument("--port", type=int, default=8769)
    args = parser.parse_args()
    if not (args.check or args.serve):
        parser.error("choose --check or --serve")
    runtime = find_runtime()
    root = data_root(args.data_dir)
    if args.check:
        return check(runtime, root, args.board)
    return serve(runtime, args.board, args.state, args.port, root)


if __name__ == "__main__":
    raise SystemExit(main())
