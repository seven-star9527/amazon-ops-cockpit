"""Read-only SIF discovery schema/sample probe; never prints credentials."""

from __future__ import annotations

import getpass
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from b_ops.collect.sif import SifClient


def main() -> None:
    key = os.getenv("SIF_MCP_KEY") or getpass.getpass("SIF key: ")
    client = SifClient("https://mcp.sif.com/mcp", key)
    del key
    wanted = ("market_discover_competitors", "market_get_keyword_root_competitors",
              "market_get_keyword_competition", "market_screen_keyword_opportunities",
              "market_get_asin_keyword_signals")
    result = {}
    for tool in client.tools():
        name = tool.get("name")
        if name not in wanted:
            continue
        schema = tool.get("inputSchema") or {}
        result[name] = {"required": schema.get("required"),
                        "properties": {key: {"type": value.get("type"),
                                              "description": str(value.get("description") or "")[:140]}
                                       for key, value in (schema.get("properties") or {}).items()}}
    try:
        sample = client.call("market_discover_competitors", {
            "keyword": "kids knife set for chopping", "country": "UK",
            "my_asin": "B0FGTVP62B", "max_results": 3,
        })
        result["sample"] = {"keys": list(sample) if isinstance(sample, dict) else [],
                            "list_shapes": {key: {"length": len(value),
                                                  "first": value[0] if value else None}
                                            for key, value in sample.items() if isinstance(value, list)}
                            if isinstance(sample, dict) else sample}
    except Exception as exc:
        result["sample"] = {"error_type": type(exc).__name__, "message": str(exc)[:120]}
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
