"""Render a stored B-line board.json as a standalone offline HTML snapshot."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from b_ops.render import render_board


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("run_id", help="B-line run ID")
    parser.add_argument("--supplement", action="append", default=[],
                        help="SIF supplement query ID to embed in a separate read-only HTML")
    args = parser.parse_args()
    folder = ROOT / "storage" / "runs" / args.run_id
    for query_id in args.supplement:
        if Path(query_id).name != query_id or not query_id.startswith("sif-"):
            parser.error("--supplement must be a SIF query ID")
    paths = [folder / "supplements" / query_id / "summary.json" for query_id in args.supplement]
    output = folder / ("board-ads-v7-sif.html" if paths else "board-ads-v7.html")
    print(render_board(folder / "board.json", output, supplement_paths=paths))


if __name__ == "__main__":
    main()
