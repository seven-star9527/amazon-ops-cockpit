"""Collect SIF Listing traffic composition for selected ASINs (read-only)."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from b_ops.collect.sif import SifClient


def _ratio(value):
    try:
        return round(float(value), 4)
    except (TypeError, ValueError):
        return None


def _traffic(payload: dict, days: int) -> dict:
    overview = payload.get("overview") or {}
    natural = overview.get("nf") or {}
    advertising = overview.get("ad") or {}
    ad = payload.get("ad") or {}
    recommend = payload.get("recommend") or {}
    return {
        "days": days,
        "total": payload.get("total"),
        "natural_ratio": _ratio(natural.get("ratio")),
        "ad_ratio": _ratio(advertising.get("ratio")),
        "sp_ratio": _ratio((ad.get("sp") or {}).get("ratio")),
        "recommend_ratio": _ratio((ad.get("recommend") or {}).get("ratio")),
        "sbv_ratio": _ratio((ad.get("sbv") or {}).get("ratio")),
        "recommend_sources": [
            {"name": (value or {}).get("name") or key, "ratio": _ratio((value or {}).get("ratio"))}
            for key, value in sorted(recommend.items(), key=lambda item: float((item[1] or {}).get("ratio") or 0), reverse=True)
        ][:6],
        "data_notice": payload.get("data_notice"),
    }


def collect(board_path: Path, *, asins: set[str] | None = None, limit: int = 20, days: int = 30) -> dict:
    key = os.getenv("SIF_MCP_KEY")
    if not key:
        raise SystemExit("SIF_MCP_KEY is required")
    board = json.loads(board_path.read_text(encoding="utf-8"))
    products = list((board.get("products") or {}).values())
    if asins:
        products = [p for p in products if str(p.get("asin") or "").upper() in asins]
    products = products[:max(0, limit)]
    client = SifClient(os.getenv("SIF_MCP_URL") or "https://mcp.sif.com/mcp", key)
    items = []
    for product in products:
        site = str(product.get("site") or "").upper()
        asin = str(product.get("asin") or "").upper()
        if not site or not asin:
            continue
        item = {"sid": product.get("sid"), "site": site, "asin": asin,
                "collected_at": dt.datetime.now().astimezone().isoformat(timespec="seconds")}
        try:
            payload = client.call("ops_get_listing_traffic_overview", {
                "asin": asin, "country": site, "timePieceType": "latelyDay",
                "timePieceValue": str(days), "isListingSearch": False,
            })
            item["traffic"] = _traffic(payload if isinstance(payload, dict) else {}, days)
        except Exception as exc:
            item["error"] = type(exc).__name__
        items.append(item)
    return {"schema": "amazon-ops-b/listing-insights/1", "source": "sif",
            "run_id": board.get("run_id"), "collected_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
            "products": items}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--board", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--asin", action="append", default=[])
    args = ap.parse_args()
    data = collect(args.board, asins={a.upper() for a in args.asin} or None, limit=args.limit, days=args.days)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"products": len(data["products"]), "out": str(args.out)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
