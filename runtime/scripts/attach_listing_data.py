"""Attach same-day Listing evidence to an existing B/PMC board without touching inventory math.

Reads Lingxing erp_listing from the captured export, optional 30-day return
analytics from the read-only MCP, and an optional SellerSprite supplement.
The board's inventory projection and shipment plan are never recalculated here.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from b_ops.collect.lingxing import LingxingClient, extract_data


def _rows(export: dict, key: str) -> list[dict]:
    try:
        return export["tools"][key]["response"]["data"]["data"]["list"]
    except (KeyError, TypeError):
        return []


def _content(row: dict) -> dict:
    return {
        "title": str(row.get("item_name") or "").strip(),
        "main_image_url": str(row.get("small_image_url") or "").strip() or None,
        "bullets": None,
        "gallery_urls": None,
        "source": "erp_listing",
    }


def _return_analysis(row: dict, start: str, end: str) -> dict:
    reason = row.get("mainReturnReason")
    if isinstance(reason, dict):
        main_reason = str(reason.get("reason") or "").strip() or None
        reason_share = reason.get("reasonRation")
    else:
        main_reason, reason_share = None, None
    return {
        "rate": row.get("curReturnGoodsVolumeRatio"),
        "prior_rate": row.get("preReturnGoodsVolumeRatio"),
        "returns": row.get("curReturnGoodsCount"),
        "units": row.get("curVolume"),
        "main_reason": main_reason,
        "reason_share": reason_share,
        "period": [start, end],
        "source": "analytics_order_analysis_lists",
    }


def attach(board_path: Path, export_path: Path, *, with_returns: bool = True,
            supplement_path: Path | None = None, insights_path: Path | None = None) -> dict:
    board = json.loads(board_path.read_text(encoding="utf-8"))
    export = json.loads(export_path.read_text(encoding="utf-8"))
    as_of = str(board.get("as_of_date") or export.get("as_of") or "")
    end = as_of
    start = (__import__("datetime").date.fromisoformat(as_of) - __import__("datetime").timedelta(days=29)).isoformat()
    listings = _rows(export, "erp_listing")
    by_key = {(str(r.get("store_id") or ""), str(r.get("asin") or "").upper()): r for r in listings}
    products = board.get("products") or {}
    content_hits = 0
    for product in products.values():
        row = by_key.get((str(product.get("sid") or ""), str(product.get("asin") or "").upper()))
        if row:
            product["content"] = _content(row)
            content_hits += 1
    return_hits = 0
    if with_returns:
        key = os.getenv("LINGXING_MCP_KEY")
        if not key:
            raise SystemExit("LINGXING_MCP_KEY is required for --returns")
        client = LingxingClient(os.getenv("LINGXING_MCP_URL") or "https://openmcp.lingxing.com/mcp-servers/lingxing-mcp", key)
        stores = sorted({str(p.get("sid")) for p in products.values() if p.get("sid")})
        returns = {}
        for sid in stores:
            data = extract_data(client.read("analytics_order_analysis_lists", {
                "asinType": "asin", "dateType": 0, "startDate": start, "endDate": end,
                "storeId": [sid], "offset": 0, "length": 1000,
            }))
            for row in (data.get("records") or []):
                if not isinstance(row, dict) or not row.get("asin"):
                    continue
                returns[(str(row.get("sid") or sid), str(row.get("asin")).upper())] = _return_analysis(row, start, end)
        for product in products.values():
            item = returns.get((str(product.get("sid") or ""), str(product.get("asin") or "").upper()))
            if item:
                product["return_analysis"] = item
                return_hits += 1
    insight_hits = 0
    if insights_path:
        insights = json.loads(insights_path.read_text(encoding="utf-8"))
        if insights.get("schema") != "amazon-ops-b/listing-insights/1":
            raise SystemExit("invalid listing insights schema")
        for item in insights.get("products") or []:
            for product in products.values():
                if str(product.get("sid")) == str(item.get("sid")) and str(product.get("asin")).upper() == str(item.get("asin")).upper():
                    product["listing_insights"] = {"source": insights.get("source") or "sif",
                                                   "collected_at": item.get("collected_at") or insights.get("collected_at"),
                                                   "traffic": item.get("traffic")}
                    insight_hits += 1
                    break
    supplement_hits = 0
    if supplement_path:
        supplement = json.loads(supplement_path.read_text(encoding="utf-8"))
        if supplement.get("schema") != "amazon-ops-b/listing-supplement/1":
            raise SystemExit("invalid listing supplement schema")
        for item in supplement.get("products") or []:
            for product in products.values():
                if str(product.get("sid")) == str(item.get("sid")) and str(product.get("asin")).upper() == str(item.get("asin")).upper():
                    external = {k: v for k, v in item.items() if k not in {"sid", "asin", "site"}}
                    external["source"] = supplement.get("source") or "sellersprite_mcp"
                    external["collected_at"] = item.get("collected_at") or supplement.get("collected_at")
                    product["listing_external"] = external
                    supplement_hits += 1
                    break
    board["listing_evidence"] = {
        "as_of": as_of, "return_period": [start, end],
        "content_hits": content_hits, "return_hits": return_hits, "supplement_hits": supplement_hits,
        "insight_hits": insight_hits,
        "sources": ["erp_listing"] + (["analytics_order_analysis_lists"] if with_returns else [])
        + (["sellersprite_mcp"] if supplement_hits else []) + (["sif_listing"] if insight_hits else []),
    }
    board_path.write_text(json.dumps(board, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return board["listing_evidence"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--board", type=Path, required=True)
    ap.add_argument("--export", type=Path, required=True)
    ap.add_argument("--no-returns", action="store_true")
    ap.add_argument("--supplement", type=Path)
    ap.add_argument("--insights", type=Path)
    args = ap.parse_args()
    print(json.dumps(attach(args.board, args.export, with_returns=not args.no_returns,
                            supplement_path=args.supplement, insights_path=args.insights), ensure_ascii=False))


if __name__ == "__main__":
    main()
