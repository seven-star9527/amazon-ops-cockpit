"""Read-only Lingxing ad-report shape probe; never prints credentials."""

from __future__ import annotations

import getpass
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from b_ops.collect.lingxing import LingxingClient, extract_data


def main() -> None:
    key = os.getenv("LINGXING_MCP_KEY") or getpass.getpass("Lingxing key: ")
    client = LingxingClient("https://openmcp.lingxing.com/mcp-servers/lingxing-mcp", key)
    del key
    auth = extract_data(client.read("ad_auth_shops", {"page": 1, "length": 1000}))
    profile = str(auth[0]["profile_id"])
    output = {}
    for tool in ("ad_campaign_keyword_report", "ad_campaign_report", "ad_campaign_product_report"):
        try:
            data = extract_data(client.read(tool, {
                "report_date": "2026-09-28 - 2026-10-11", "profile_ids": [profile],
                "page": 1, "length": 3, "sort_field": "spends", "sort_type": "desc",
            }))
            rows = (data.get("data") or data.get("list") or []) if isinstance(data, dict) else data
            detail = next((row for row in rows if row.get("keyword_id") or row.get("campaign_id")
                           or row.get("ad_group_id")), None)
            selected = ("profile_id", "sponsored_type", "campaign_id", "campaign_name",
                        "ad_group_id", "ad_group_name", "keyword_id", "keyword_text",
                        "targeting_text", "match_type", "state", "ad_group_state",
                        "campaign_state", "bid", "default_bid", "bidding", "adjustmentsBidMap",
                        "is_apply_time", "impressions", "clicks", "spends", "orders", "sales")
            selected += ("budget", "daily_budget", "budget_type", "budget_amount", "cost_type")
            output[tool] = {"status": "ok", "keys": list(data) if isinstance(data, dict) else [],
                            "returned": len(rows), "summary_rows": sum(not any(row.get(k) for k in
                                ("keyword_id", "campaign_id", "ad_group_id")) for row in rows),
                            "detail_keys": list(detail) if detail else [],
                            "row": {key: detail.get(key) for key in selected} if detail else None}
        except Exception as exc:
            output[tool] = {"status": "error", "error_type": type(exc).__name__,
                            "message": str(exc)[:120]}
    print(json.dumps(output, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
