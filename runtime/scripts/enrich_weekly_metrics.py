"""Attach the full Lingxing weekly metric set to an existing board offline."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(str(value).replace(',', ''))
    except (TypeError, ValueError):
        return None


def enrich(board_path: Path, performance_dir: Path) -> dict:
    board = json.loads(board_path.read_text(encoding="utf-8"))
    by_key = {(str(product.get("sid")), str(product.get("asin") or "").upper()): product
              for product in (board.get("products") or {}).values()}
    rows = matched = 0
    for path in sorted(performance_dir.glob("performance_*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        request = payload.get("request") or {}
        start = str(request.get("start_date") or "")
        for row in payload.get("rows") or []:
            rows += 1
            asin = str(row.get("asin") or "").strip().upper()
            sids = [str(value) for value in (row.get("sids") or [])]
            if not asin or not sids:
                continue
            product = by_key.get((sids[0], asin))
            if not product:
                continue
            week = next((item for item in product.get("weeks") or [] if str(item.get("start")) == start), None)
            if not week:
                continue
            week["impressions"] = number(row.get("impressions"))
            week["ad_orders"] = number(row.get("ad_order_quantity"))
            week["natural_orders"] = number(row.get("nature_order_items"))
            week["acos"] = number(row.get("acos"))
            week["acoas"] = number(row.get("tacos"))
            week["cpc"] = number(row.get("cpc"))
            week["ad_cvr"] = number(row.get("ad_cvr"))
            week["natural_order_share"] = number(row.get("nature_order_rate"))
            ad_clicks = number(row.get("clicks"))
            sessions = number(row.get("sessions_total"))
            orders = number(row.get("order_items"))
            units = number(row.get("volume"))
            if units is not None:
                week["daily_units"] = round(units / 7, 2)
            if sessions and orders is not None:
                week["total_cvr"] = round(orders / sessions, 4)
            if week["ad_orders"] is not None and orders:
                week["ad_order_share"] = round(week["ad_orders"] / orders, 4)
            if ad_clicks is not None and week["impressions"]:
                week["ad_click_rate"] = round(ad_clicks / week["impressions"], 5)
            if sessions is not None and ad_clicks is not None and 0 <= ad_clicks <= sessions:
                week["natural_sessions_est"] = sessions - ad_clicks
            matched += 1
    board["weekly_metric_evidence"] = {"rows": rows, "matched": matched,
                                       "source": "query_product_performance_asin_lists",
                                       "fields": ["impressions", "ad_orders", "natural_orders", "acos", "acoas",
                                                  "cpc", "ad_cvr", "natural_order_share", "daily_units",
                                                  "total_cvr", "ad_order_share", "ad_click_rate"]}
    board_path.write_text(json.dumps(board, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return board["weekly_metric_evidence"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--board", type=Path, required=True)
    ap.add_argument("--performance-dir", type=Path, required=True)
    args = ap.parse_args()
    print(json.dumps(enrich(args.board, args.performance_dir), ensure_ascii=False))


if __name__ == "__main__":
    main()
