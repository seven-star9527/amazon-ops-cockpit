"""Interactive fresh read-only run; credentials are prompted without echo."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import re
from pathlib import Path
import sys
from datetime import date

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from b_ops.collect.lingxing import LingxingClient
from b_ops.collect.refresh import refresh
from b_ops.collect.replay import ReplayLingxing, ReplaySif, ResumeSif, ExtendSif
from b_ops.collect.sif import SifClient
from b_ops.paths import data_root
from b_ops.collect.cache import CachedSif
import hashlib


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--sif-max-calls", type=int, default=100)
    parser.add_argument("--sif-limit", type=int, default=25)
    parser.add_argument("--as-of", type=date.fromisoformat,
                        help="Historical B-line replay date only (YYYY-MM-DD); never labels replay as a fresh read")
    parser.add_argument("--no-sif", action="store_true")
    parser.add_argument("--replay-lingxing", help="Recalculate from this B-line Lingxing raw read")
    parser.add_argument("--replay-sif", help="Recalculate from recorded B-line SIF responses only")
    parser.add_argument("--resume-sif", help="Reuse exact calls from an interrupted same-day B-line SIF read, then fetch missing calls live")
    parser.add_argument("--extend-sif", help="Reuse hash-verified exact calls from a completed same-day B-line batch, then fetch only new SIF calls")
    parser.add_argument("--competitor-asins", nargs="*", metavar="ASIN",
                        help="Restrict new competitor discovery to these ASINs for a focused QA batch")
    args = parser.parse_args()
    if sum(bool(value) for value in (args.no_sif, args.replay_sif, args.resume_sif, args.extend_sif)) > 1:
        raise SystemExit("choose only one SIF source mode")
    if args.competitor_asins and not all(re.fullmatch(r"B[A-Z0-9]{9}", value.upper()) for value in args.competitor_asins):
        raise SystemExit("--competitor-asins requires valid Amazon ASINs")
    if args.as_of and not args.replay_lingxing:
        raise SystemExit("--as-of is only valid with a B-line Lingxing raw replay")
    root = data_root(args.data_dir)
    lk = None if args.replay_lingxing else (os.getenv("LINGXING_MCP_KEY") or getpass.getpass("Lingxing MCP key: "))
    sk = None if args.no_sif or args.replay_sif else (os.getenv("SIF_MCP_KEY") or getpass.getpass("SIF MCP key: "))
    if args.replay_lingxing:
        if not args.replay_lingxing.startswith("b-") or any(ch in args.replay_lingxing for ch in ("/", "\\", ".")):
            raise SystemExit("invalid B-line replay run ID")
        lx = ReplayLingxing(root / "storage" / "runs" / args.replay_lingxing)
    else:
        lx = LingxingClient(os.getenv("LINGXING_MCP_URL") or "https://openmcp.lingxing.com/mcp-servers/lingxing-mcp", lk)
    if args.replay_sif:
        if not args.replay_sif.startswith("b-") or any(ch in args.replay_sif for ch in ("/", "\\", ".")):
            raise SystemExit("invalid B-line replay run ID")
        sf = ReplaySif(root / "storage" / "runs" / args.replay_sif)
    elif args.resume_sif:
        if (not re.fullmatch(r"b-[0-9]{8}-[0-9]{6}-[a-z0-9]+", args.resume_sif)
                or args.resume_sif[2:10] != date.today().strftime("%Y%m%d")):
            raise SystemExit("SIF resume source must be an interrupted same-day B-line run ID")
        source = root / "storage" / "runs" / args.resume_sif
        if not (source / "raw" / "sif").is_dir() or (source / "manifest.json").is_file():
            raise SystemExit("SIF resume source must contain interrupted raw responses without a manifest")
        sf = ResumeSif(source, SifClient(os.getenv("SIF_MCP_URL") or "https://mcp.sif.com/mcp", sk))
    elif args.extend_sif:
        if (not re.fullmatch(r"b-[0-9]{8}-[0-9]{6}-[a-z0-9]+", args.extend_sif)
                or args.extend_sif[2:10] != date.today().strftime("%Y%m%d")):
            raise SystemExit("SIF extension source must be a complete same-day B-line run ID")
        source = root / "storage" / "runs" / args.extend_sif
        sf = ExtendSif(source, SifClient(os.getenv("SIF_MCP_URL") or "https://mcp.sif.com/mcp", sk))
    else:
        sf = SifClient(os.getenv("SIF_MCP_URL") or "https://mcp.sif.com/mcp", sk) if sk else None
    if sf and sk:
        scope = hashlib.sha256(((os.getenv("SIF_MCP_URL") or "https://mcp.sif.com/mcp") + sk).encode()).hexdigest()
        sf = CachedSif(root / "storage/cache/sif.sqlite3", sf, scope=scope, max_calls=args.sif_max_calls)
    del lk, sk
    print(json.dumps(refresh(root, lx, sf, today=args.as_of, sif_product_limit=args.sif_limit,
                             competitor_focus_asins={value.upper() for value in args.competitor_asins}
                             if args.competitor_asins else None), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
