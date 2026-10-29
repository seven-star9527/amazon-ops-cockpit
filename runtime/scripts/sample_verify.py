"""Reconcile representative normalized B metrics with this run's raw MCP responses."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from b_ops.collect.lingxing import extract_data
from b_ops.model.snapshot import number


ROOT=Path(__file__).resolve().parents[1]


def verify(run_id: str) -> dict:
    if not re.fullmatch(r"b-[0-9]{8}-[0-9]{6}-[a-z0-9]+",run_id):
        raise ValueError("invalid run ID")
    run=ROOT/"storage"/"runs"/run_id
    board=json.loads((run/"board.json").read_text(encoding="utf-8"))
    manifest=json.loads((run/"manifest.json").read_text(encoding="utf-8"))
    by_tool={}
    for source in manifest["source_calls"]:
        by_tool.setdefault(source["tool"],[]).append(json.loads((run/source["file"]).read_text(encoding="utf-8")))
    products=list(board["products"].values())
    multi=next(p for p in products if len(p["skus"])>1 and p["stock"].get("source")=="get_fba_stock_list")
    sid,asin=multi["sid"],multi["asin"]
    stock_rows=[]
    for source in by_tool["get_fba_stock_list"]:
        data=extract_data(source["response"])
        rows=data.get("list") or data.get("data") or []
        stock_rows.extend(row for row in rows if str(row.get("sid") or row.get("s_id"))==sid and str(row.get("asin"))==asin)
    assert len(stock_rows)>1
    raw_sellable=sum(number(row.get("afn_fulfillable_quantity")) or 0 for row in stock_rows)
    assert multi["stock"]["sellable"]==raw_sellable
    measured=next(week for week in multi["weeks"] if week["quality"]=="measured")
    raw_week=None
    for source in by_tool["query_product_performance_asin_lists"]:
        data=extract_data(source["response"])
        rows=data.get("data") or data.get("list") or []
        for row in rows:
            if str(row.get("asin"))==asin and row.get("rdate")==f"{measured['start']}~{measured['end']}":
                raw_week=row;break
        if raw_week is not None:break
    assert raw_week is not None
    assert number(raw_week.get("volume"))==measured["units"]
    assert number(raw_week.get("sessions_total"))==measured["sessions_total"]
    shared=next(action for action in board["actions"] if action["shared_group"] and len(action["affected_asins"])>1)
    assert sum(item["action_key"]==shared["action_key"] for item in board["actions"])==1
    matched=sum(any(action["action_key"]==shared["action_key"] for action in p["actions"])
                for p in products)
    assert matched>=2
    return {"sample_multi_sku_asin":asin,"sku_count":len(multi["skus"]),
            "fba_source_rows":len(stock_rows),"fba_sellable_raw":raw_sellable,
            "weekly_sample":measured["label"],"units_raw":measured["units"],
            "total_clicks_raw":measured["sessions_total"],
            "shared_action_asins":len(shared["affected_asins"]),"shared_action_present_on_products":matched,
            "chinese_names":sum(any(ord(char)>127 for char in p["name"]) for p in products),
            "source_english_fallbacks":sum(all(ord(char)<128 for char in p["name"]) for p in products)}


def main():
    parser=argparse.ArgumentParser();parser.add_argument("run_id");args=parser.parse_args()
    print(json.dumps(verify(args.run_id),ensure_ascii=False,indent=2))


if __name__=="__main__":main()
