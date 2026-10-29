"""Assemble sanitized, same-day Lingxing MCP reads into the PMC input contract."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


SOURCE_IDS = ("erp_listing", "get_fba_stock_list", "query_fba_valid_list",
              "settings_message_inventory_list")


def _read(path: Path, as_of: str | None):
    data = json.loads(path.read_text(encoding="utf-8"))
    if not data.get("as_of") or (as_of and data["as_of"] != as_of):
        raise ValueError(f"source date mismatch: {path.name}")
    rows = data.get("rows")
    if not isinstance(rows, (dict, list)):
        raise ValueError(f"source rows invalid: {path.name}")
    if isinstance(rows, list) and data.get("reported_total") is not None and len(rows) != data["reported_total"]:
        raise ValueError(f"source page incomplete: {path.name}")
    return data


def assemble(source_dir: Path) -> dict:
    source_dir = Path(source_dir)
    paths = [source_dir / f"{name}.json" for name in SOURCE_IDS]
    performance_paths = sorted(source_dir.glob("performance_*.json"))
    if not performance_paths:
        raise ValueError("daily product-performance sources missing")
    sources = {}
    as_of = None
    for path in paths + performance_paths:
        current = _read(path, as_of)
        as_of = as_of or current["as_of"]
        sources[path.name] = current
    daily = []
    seen = set()
    dates = set()
    for path in performance_paths:
        source = sources[path.name]
        for row in source["rows"]:
            asin = str(row.get("asin") or "").strip().upper()
            if not asin or asin == "-":
                continue
            sid = str((row.get("sids") or [row.get("sid")])[0])
            day = str(row.get("rdate") or "")[:10]
            if not sid or not day:
                raise ValueError(f"daily identity missing: {path.name}")
            key = (sid, asin, day)
            if key in seen:
                raise ValueError(f"duplicate daily store-ASIN: {path.name}")
            seen.add(key)
            dates.add(day)
            daily.append(row)
    if max(dates) != as_of:
        raise ValueError("last daily observation does not match as_of")
    def wrapped(value):
        return {"response": {"code": 1, "data": {"code": 0, "data": value}}}
    tools = {
        "erp_listing": wrapped({"list": sources["erp_listing.json"]["rows"]}),
        "get_fba_stock_list": {"response": {"code": 1, "data": {"list": sources["get_fba_stock_list.json"]["rows"]}}},
        "query_fba_valid_list": wrapped({"list": sources["query_fba_valid_list.json"]["rows"]}),
        "settings_message_inventory_list": wrapped(sources["settings_message_inventory_list.json"]["rows"]),
        "platform_v2_page_list": wrapped({"statisticsList": []}),
        "query_product_performance_asin_lists": wrapped({"list": daily}),
        "analytics_show_product_list": {"response": {"code": 1, "data": {"code": 0, "msg": "permission-missing"}}},
    }
    audit = {
        "as_of": as_of,
        "daily_rows": len(daily),
        "daily_dates": len(dates),
        "capabilities": {"platform_v2_page_list": "unavailable; complete daily product performance used",
                         "analytics_show_product_list": "permission-missing"},
        "source_files": {name: hashlib.sha256((source_dir / name).read_bytes()).hexdigest() for name in sources},
    }
    return {"as_of": as_of, "tools": tools, "source_audit": audit}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sources", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = assemble(args.sources)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(json.dumps(result["source_audit"], ensure_ascii=False))


if __name__ == "__main__":
    main()
