"""Read-only Lingxing schema/sample probe without persisting credentials."""

from __future__ import annotations

import argparse
import datetime as dt
import os
import json
import sys
from pathlib import Path
from typing import Any


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from b_ops.collect.lingxing import LingxingClient


TOOL_IDS = (
    "erp_listing",
    "get_fba_stock_list",
    "query_fba_valid_list",
    "settings_message_inventory_list",
    "platform_v2_page_list",
    "query_product_performance_asin_lists",
    "analytics_show_product_list",
)
SECRET_KEY_NAMES = {"x-mcp-key", "authorization", "api_key", "apikey", "token", "secret"}


def find_authorized_connection() -> tuple[str, str]:
    """Only explicit process configuration; never inspect another application's history."""
    url, key = os.getenv("LINGXING_MCP_URL", ""), os.getenv("LINGXING_MCP_KEY", "")
    if not url or not key:
        raise RuntimeError("请配置 LINGXING_MCP_URL 和 LINGXING_MCP_KEY")
    return url, key


def scrub(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: ("[REDACTED]" if key.lower() in SECRET_KEY_NAMES else scrub(child))
            for key, child in value.items()
        }
    if isinstance(value, list):
        return [scrub(child) for child in value]
    return value


PRODUCT_PERFORMANCE_FIELDS = {
    "asin", "asins", "sids", "rdate", "volume", "seller_store_countries",
    "afn_fulfillable_quantity", "reserved_customerorders", "afn_reserved_quantity",
    "reserved_fc_transfers", "reserved_fc_processing",
    "afn_inbound_receiving_quantity", "afn_inbound_shipped_quantity",
}


def compact_product_performance_response(response: dict[str, Any]) -> dict[str, Any]:
    """Keep only demand and inventory fields before saving a potentially large 60-day response."""
    result = dict(response)
    outer = dict(result.get("data") or {})
    payload = dict(outer.get("data") or {})
    rows = payload.get("list") or []
    payload["list"] = [
        {key: value for key, value in row.items() if key in PRODUCT_PERFORMANCE_FIELDS}
        for row in rows
        if isinstance(row, dict)
    ]
    outer["data"] = payload
    result["data"] = outer
    return result


def build_sample_requests(as_of: str) -> dict[str, dict[str, Any]]:
    """Build bounded, read-only requests that expose each inventory source shape."""
    end = dt.date.fromisoformat(as_of)
    start_60 = end - dt.timedelta(days=59)
    start_90 = end - dt.timedelta(days=89)
    return {
        "erp_listing": {
            "offset": 0,
            "length": 20,
            "pvi_ids": "",
            "fulfillment_channel_type": "FBA",
        },
        "get_fba_stock_list": {
            "offset": 0,
            "length": 20,
            "fulfillment_channel_type": "FBA",
            "is_hide_zero_stock": "0",
            "is_parant_asin_merge": "0",
        },
        "query_fba_valid_list": {
            "offset": 0,
            "length": 20,
            "dataType": 1,
            "analysisMode": 2,
            "fulfillmentChannelType": "FBA",
            "searchField": "asin",
            "searchValue": "",
            "restockStatus": [0],
        },
        "settings_message_inventory_list": {
            "modelIdList": [4, 5, 22, 23],
            "current": 1,
            "size": 20,
            "showStatus": 1,
            "startTime": start_90.isoformat(),
            "selectType": 1,
            "endTime": end.isoformat(),
        },
        "platform_v2_page_list": {
            "currencyCode": "",
            "dataType": "1",
            "dateUnit": "4",
            "start": start_60.isoformat(),
            "end": end.isoformat(),
            "resultType": "1",
            "searchType": 3,
            "pageNum": 1,
            "pageSize": 20,
        },
        "query_product_performance_asin_lists": {
            "offset": 0,
            "length": 20,
            "start_date": start_60.isoformat(),
            "end_date": end.isoformat(),
            "date_type": "purchase",
            "date_view_type": "day",
            "date_view_order_type": 1,
            "date_sort_type": "asc",
            "summary_field": "asin",
            "summary_field_level1": "asin",
            "turn_on_summary": 1,
            "sort_field": "volume",
            "sort_type": "desc",
            "currency_code": "CNY",
        },
        "analytics_show_product_list": {
            "start_date": start_90.isoformat(),
            "end_date": end.isoformat(),
            "time_type": 1,
            "offset": 0,
            "length": 20,
        },
    }


def build_account_requests(as_of: str) -> dict[str, dict[str, Any]]:
    """Build bounded requests sized to cover this account's current inventory set."""
    requests = build_sample_requests(as_of)
    requests["erp_listing"]["length"] = 500
    requests["get_fba_stock_list"]["length"] = 500
    requests["query_fba_valid_list"]["length"] = 500
    requests["query_fba_valid_list"]["restockStatus"] = [0, 1]
    requests["settings_message_inventory_list"]["size"] = 200
    requests["platform_v2_page_list"]["pageSize"] = 200
    requests["query_product_performance_asin_lists"]["length"] = 10000
    requests["analytics_show_product_list"]["length"] = 200
    return requests


def discover(output: Path) -> None:
    url, key = find_authorized_connection()
    client = LingxingClient(url=url, key=key)
    capabilities: dict[str, Any] = {"source": "Lingxing MCP", "mode": "read-only", "tools": {}}
    for tool_id in TOOL_IDS:
        try:
            response = client._call("search", {"toolId": tool_id})
            schema = response.get("data") if isinstance(response, dict) else None
            if not isinstance(schema, dict):
                raise RuntimeError("搜索结果缺少 data")
            tool_type = schema.get("toolType")
            if tool_type != "read":
                raise RuntimeError(f"拒绝非只读工具: {tool_type}")
            capabilities["tools"][tool_id] = scrub(schema)
            print(f"schema_ok {tool_id}")
        except Exception as exc:  # Keep discovery useful when individual permissions differ.
            safe_message = str(exc).replace(key, "[REDACTED]")[:500]
            capabilities["tools"][tool_id] = {
                "error": type(exc).__name__,
                "message": safe_message,
                "available": False,
            }
            print(f"schema_unavailable {tool_id} {type(exc).__name__}: {safe_message}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(capabilities, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved {output.name} tools={len(capabilities['tools'])}")


def pull_requests(output: Path, as_of: str, requests: dict[str, dict[str, Any]], mode: str) -> None:
    """Pull a fixed allowlist of real-account read sources; never calls a write tool."""
    url, key = find_authorized_connection()
    client = LingxingClient(url=url, key=key)
    payload: dict[str, Any] = {
        "source": "Lingxing MCP",
        "mode": mode,
        "as_of": as_of,
        "tools": {},
    }
    for tool_id, params in requests.items():
        try:
            response = client.read(tool_id, params)
            if tool_id == "query_product_performance_asin_lists":
                response = compact_product_performance_response(response)
            payload["tools"][tool_id] = {
                "request": scrub(params),
                "response": scrub(response),
            }
            print(f"sample_ok {tool_id}")
        except Exception as exc:
            safe_message = str(exc).replace(key, "[REDACTED]")[:1000]
            payload["tools"][tool_id] = {
                "request": scrub(params),
                "error": type(exc).__name__,
                "message": safe_message,
            }
            print(f"sample_unavailable {tool_id} {type(exc).__name__}: {safe_message}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved {output.name} tools={len(payload['tools'])}")


def pull_samples(output: Path, as_of: str) -> None:
    pull_requests(
        output,
        as_of,
        build_sample_requests(as_of),
        "read-only-real-account-samples",
    )


def pull_account(output: Path, as_of: str) -> None:
    pull_requests(
        output,
        as_of,
        build_account_requests(as_of),
        "read-only-real-account-full-page",
    )


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--discover", action="store_true")
    parser.add_argument("--pull-samples", action="store_true")
    parser.add_argument("--pull-account", action="store_true")
    parser.add_argument("--as-of", default=dt.date.today().isoformat())
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if sum((args.discover, args.pull_samples, args.pull_account)) != 1:
        raise SystemExit("必须且只能选择 --discover、--pull-samples 或 --pull-account")
    if args.discover:
        discover(args.output)
    elif args.pull_samples:
        pull_samples(args.output, args.as_of)
    else:
        pull_account(args.output, args.as_of)


if __name__ == "__main__":
    main()
