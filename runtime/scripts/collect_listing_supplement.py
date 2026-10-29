"""Collect a bounded SellerSprite Listing supplement through MCP.

The key is read only from SELLERSPRITE_MCP_KEY. It is never written to the
supplement, board, logs, or command output.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from b_ops.collect.transport import JsonRpcHttp, content_object, unpack_rpc


def _client() -> JsonRpcHttp:
    key = os.getenv("SELLERSPRITE_MCP_KEY")
    if not key:
        raise SystemExit("SELLERSPRITE_MCP_KEY is required")
    url = os.getenv("SELLERSPRITE_MCP_URL") or "https://mcp.sellersprite.com/mcp"
    client = JsonRpcHttp(url, key, provider="sellersprite")
    client.post("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                               "clientInfo": {"name": "amazon-ops-b-listing", "version": "1"}})
    client.post("notifications/initialized", {})
    return client


def _call(client: JsonRpcHttp, name: str, arguments: dict) -> dict:
    return content_object(unpack_rpc(client.post("tools/call", {"name": name, "arguments": arguments})))


def _features(detail: dict) -> list[str]:
    values = detail.get("features")
    if isinstance(values, list):
        return [str(v).strip() for v in values if str(v or "").strip()]
    return []


def _reviews(payload: dict) -> list[dict]:
    rows = payload.get("items") or payload.get("list") or payload.get("records") or payload.get("data") or []
    if isinstance(rows, dict):
        rows = rows.get("items") or rows.get("list") or rows.get("records") or []
    out = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        out.append({k: row.get(k) for k in ("star", "rating", "title", "content", "date", "verified",
                                             "likes", "author", "authorLabels", "skus") if k in row})
    return out


def collect(board_path: Path, *, limit: int = 20, only: set[str] | None = None,
            review_size: int = 20) -> dict:
    board = json.loads(board_path.read_text(encoding="utf-8"))
    products = list((board.get("products") or {}).values())
    if only:
        products = [p for p in products if str(p.get("asin") or "").upper() in only]
    products = products[:max(0, limit)]
    client = _client()
    items = []
    for product in products:
        site = str(product.get("site") or "").upper()
        asin = str(product.get("asin") or "").upper()
        if not site or not asin:
            continue
        item = {"sid": product.get("sid"), "site": site, "asin": asin, "collected_at": dt.datetime.now().astimezone().isoformat(timespec="seconds")}
        try:
            detail = _call(client, "asin_detail", {
                "marketplace": site, "asin": asin,
                "returnFields": "asin,title,brand,price,rating,ratings,reviews,imageUrl,features,badge,lqs,overview",
            })
            if isinstance(detail, dict) and isinstance(detail.get("data"), dict):
                detail = detail["data"]
            if isinstance(detail, dict):
                item.update({
                    "title": detail.get("title"),
                    "brand": detail.get("brand"),
                    "rating": detail.get("rating"),
                    "ratings": detail.get("ratings"),
                    "reviews_count": detail.get("reviews"),
                    "image_url": detail.get("imageUrl"),
                    "features": _features(detail),
                    "badge": detail.get("badge"),
                    "lqs": detail.get("lqs"),
                })
        except Exception as exc:
            item["detail_error"] = type(exc).__name__
        try:
            reviews = _call(client, "review", {
                "marketplace": site, "asin": asin, "starList": [1, 2, 3], "page": 1, "size": review_size,
            })
            item["reviews"] = _reviews(reviews if isinstance(reviews, dict) else {})
        except Exception as exc:
            item["reviews_error"] = type(exc).__name__
            item["reviews"] = []
        items.append(item)
    return {"schema": "amazon-ops-b/listing-supplement/1", "run_id": board.get("run_id"),
            "source": "sellersprite_mcp", "collected_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
            "products": items}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--board", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--asin", action="append", default=[])
    args = ap.parse_args()
    data = collect(args.board, limit=args.limit, only={a.upper() for a in args.asin} or None)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"products": len(data["products"]), "out": str(args.out)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
