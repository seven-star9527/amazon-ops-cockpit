"""Read-only live source probe. Keys are entered through a hidden terminal prompt."""

from __future__ import annotations

import getpass
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from b_ops.collect.lingxing import LingxingClient, extract_data
from b_ops.collect.sif import SifClient


def shape(value):
    if isinstance(value, list):
        return {"kind": "list", "length": len(value), "row_keys": sorted(value[0])[:60] if value and isinstance(value[0], dict) else []}
    if isinstance(value, dict):
        return {"kind": "object", "keys": sorted(value)[:60], "list_fields": {
            key: len(item) for key, item in value.items() if isinstance(item, list)
        }}
    return {"kind": type(value).__name__}


def main():
    lingxing_key = os.getenv("LINGXING_MCP_KEY") or getpass.getpass("Lingxing MCP key: ")
    sif_key = os.getenv("SIF_MCP_KEY") or getpass.getpass("SIF MCP key: ")
    lx = LingxingClient("https://openmcp.lingxing.com/mcp-servers/lingxing-mcp", lingxing_key)
    sf = SifClient("https://mcp.sif.com/mcp", sif_key)
    del lingxing_key, sif_key
    output = {"lingxing": {}, "sif": {}}
    auth_data = []
    shop_data = []
    sample_asin = None
    first_listing = None
    for tool, params in (
        ("get_multi_platform_shop_list", {"platform_code": [10001]}),
        ("ad_auth_shops", {"page": 1, "length": 1000}),
    ):
        try:
            response = lx.read(tool, params)
            if tool == "get_multi_platform_shop_list":
                output["lingxing"][tool] = {"outer_code": response.get("code"),
                    "inner_code": response.get("data", {}).get("code") if isinstance(response.get("data"), dict) else None,
                    "inner_msg": str(response.get("data", {}).get("msg", ""))[:100] if isinstance(response.get("data"), dict) else ""}
            data = extract_data(response)
            output["lingxing"][tool] = {"status": "verified", **shape(data)}
            if tool == "ad_auth_shops" and isinstance(data, list):
                auth_data = data
            if tool == "get_multi_platform_shop_list" and isinstance(data, list):
                shop_data = data
        except Exception as exc:
            prior = output["lingxing"].get(tool, {})
            output["lingxing"][tool] = {**prior, "status": "failed", "error_type": type(exc).__name__, "message": str(exc)[:100]}
    sids = [str(row.get("sid")) for row in auth_data if row.get("sid")]
    for tool, params in (
        ("erp_listing", {"pvi_ids": "", "sids": ",".join(sids), "offset": 0, "length": 2}),
        ("get_fba_stock_list", {"sid": ",".join(sids), "is_hide_zero_stock": "0", "offset": 0, "length": 20}),
        ("query_product_performance_asin_lists", {"sids": sids[0] if sids else "", "start_date": "2026-09-28", "end_date": "2026-10-04", "offset": 0, "length": 2}),
        ("ad_campaign_search_term_report", {"report_date": "2026-09-01 - 2026-09-30", "profile_ids": [str(auth_data[0]["profile_id"])], "page": 1, "length": 20, "sort_field": "spends", "sort_type": "desc", "with_ring": False}),
    ):
        try:
            response = lx.read(tool, params)
            data = extract_data(response)
            output["lingxing"][tool] = {"status": "verified", **shape(data)}
            if isinstance(data, dict):
                rows = data.get("list", [])
                if rows and tool == "erp_listing":
                    first_listing = rows[0]
                    sample_asin = rows[0].get("asin") or rows[0].get("asin1")
                    output["lingxing"][tool]["sample_types"] = {
                        key: type(value).__name__ for key, value in rows[0].items() if key in ("asin", "asin1", "title", "product_name", "local_name", "sku", "msku", "s_id", "sid")}
                    output["lingxing"][tool]["row_keys"] = sorted(rows[0])
                if rows and tool == "query_product_performance_asin_lists":
                    output["lingxing"][tool]["row_keys"] = sorted(rows[0])
                if tool == "ad_campaign_search_term_report":
                    detail = data.get("data") or []
                    output["lingxing"][tool]["recordsFiltered"] = data.get("recordsFiltered")
                    if detail:
                        output["lingxing"][tool]["row_keys"] = sorted(detail[0])
                if tool == "get_fba_stock_list" and "list" not in data:
                    output["lingxing"][tool]["code"] = data.get("code")
                    output["lingxing"][tool]["message"] = str(data.get("msg") or "")[:100]
        except Exception as exc:
            output["lingxing"][tool] = {"status": "failed", "error_type": type(exc).__name__, "message": str(exc)[:100]}
    try:
        tools = sf.tools()
        output["sif"]["tools"] = {"status": "verified", "count": len(tools),
                                  "relevant": [tool.get("name") for tool in tools if any(
                                      word in str(tool.get("name", "")) for word in ("asin", "keyword", "rank"))]}
    except Exception as exc:
        output["sif"]["tools"] = {"status": "failed", "error_type": type(exc).__name__, "message": str(exc)[:100]}
    if sample_asin:
        for tool, params in (
            ("market_get_asin_profile", {"asins": [sample_asin], "country": "US"}),
            ("market_get_asin_keyword_signals", {"asin": sample_asin, "country": "US", "time_type": "lately", "time_value": "7", "topN": 3}),
        ):
            try:
                output["sif"][tool] = {"status": "verified", **shape(sf.call(tool, params))}
            except Exception as exc:
                output["sif"][tool] = {"status": "failed", "error_type": type(exc).__name__, "message": str(exc)[:100]}
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
