"""离线挂接只读 API 货件数据；复用现有库存引擎，不改变面板布局。"""
import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from b_ops.collect.lingxing_supply import apply_supply
from b_ops.paths import data_root
from b_ops.run_lock import single_writer
from b_ops.render import render_board
from pmc.scripts.fuse_board import fuse_board


def attach(*, snapshot_path, supply_path, board_path, output_dir, allowed_sids):
    # Same external-data policy and lock as collection. Inputs remain untouched.
    output_dir = data_root(output_dir)
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    supply = json.loads(supply_path.read_text(encoding="utf-8"))
    board = json.loads(board_path.read_text(encoding="utf-8"))
    allowed = {str(s) for s in allowed_sids}
    if any(str(p.get("sid")) not in allowed for p in board["products"].values()):
        raise ValueError("BOARD_SCOPE_DENIED")
    enriched = apply_supply(snapshot, supply, allowed_sids=allowed)
    with single_writer(output_dir):
        snapshot_out = output_dir / "inventory-snapshot.json"
        projection_out = output_dir / "inventory-projection.json"
        board_out = output_dir / "board-pmc.json"
        if any(p.resolve() in {snapshot_out, projection_out, board_out}
               for p in (snapshot_path, supply_path, board_path)):
            raise ValueError("output must not overwrite source artifacts")
        snapshot_out.write_text(json.dumps(enriched, ensure_ascii=False), encoding="utf-8")
        subprocess.run(["node", str(ROOT / "pmc/scripts/analyze_snapshot.mjs"),
                        str(snapshot_out), str(projection_out)], check=True, cwd=ROOT)
        projection = json.loads(projection_out.read_text(encoding="utf-8"))
        result = fuse_board(board, projection)
        result.setdefault("review_context", {})["supply_api"] = enriched["metadata"]["supplyApi"]
        board_out.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        render_board(board_out, output_dir / "board-pmc.html")
    return enriched["metadata"]["supplyApi"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--supply", type=Path, required=True)
    parser.add_argument("--board", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--allowed-sids", nargs="+", required=True,
                        help="Trusted local operator scope; NANDOU must inject server-side grants")
    args = parser.parse_args()
    print(json.dumps(attach(snapshot_path=args.snapshot, supply_path=args.supply,
        board_path=args.board, output_dir=args.output_dir, allowed_sids=args.allowed_sids), ensure_ascii=False))


if __name__ == "__main__":
    main()
