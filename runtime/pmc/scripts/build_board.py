"""Rebuild the dated inventory layer and standalone B workbench from captured sources.

This is deliberately offline. Fresh Lingxing reads must first be captured and
audited as same-day source files; a historical B advertising batch remains dated.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT))

from b_ops.render import render_board
from pmc.scripts.assemble_sources import assemble
from pmc.scripts.build_real_snapshot import build_snapshot
from pmc.scripts.fuse_board import fuse_board


ANALYZER = Path(__file__).with_name("analyze_snapshot.mjs")


def build_board(source_dir: Path, shipment_path: Path, base_path: Path,
                output_dir: Path, *, scenario_path: Path | None = None) -> dict:
    for label, path in (("ETA workbook", shipment_path), ("B board", base_path)):
        if not path.is_file():
            raise ValueError(f"{label} missing: {path}")
    output_dir.mkdir(parents=True, exist_ok=True)
    export = assemble(source_dir)
    export_path = output_dir / "lingxing-account-export.json"
    export_path.write_text(json.dumps(export, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    snapshot = build_snapshot(export_path, shipment_path, scenario_path=scenario_path)
    snapshot_path = output_dir / "inventory-snapshot.json"
    snapshot_path.write_text(json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    projection_path = output_dir / "inventory-projection.json"
    subprocess.run(["node", str(ANALYZER), str(snapshot_path), str(projection_path)],
                   cwd=PROJECT, check=True)
    projection = json.loads(projection_path.read_text(encoding="utf-8"))
    base = json.loads(base_path.read_text(encoding="utf-8"))
    board = fuse_board(base, projection)
    import hashlib
    board["inventory_batch"]["eta_sha256"] = hashlib.sha256(shipment_path.read_bytes()).hexdigest()
    board["inventory_batch"]["eta_file_mtime"] = shipment_path.stat().st_mtime
    board_path = output_dir / "board-pmc.json"
    board_path.write_text(json.dumps(board, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    html_path = render_board(board_path, output_dir / "board-pmc.html")
    return {"as_of": export["as_of"], "source_audit": export["source_audit"],
            "inventory_products": len(projection["records"]),
            "matched": board["inventory_batch"]["matched_products"],
            "inventory_only": board["inventory_batch"]["inventory_only_products"],
            "base_as_of": base.get("as_of_date"), "board": str(html_path)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sources", type=Path, required=True)
    parser.add_argument("--shipments", type=Path, required=True)
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--scenarios", type=Path, default=PROJECT / "pmc/state/scenarios.json")
    args = parser.parse_args()
    result = build_board(args.sources, args.shipments, args.base, args.output_dir,
                         scenario_path=args.scenarios)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
