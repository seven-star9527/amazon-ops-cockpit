"""Search Lingxing write-tool definitions only; never call action."""

from __future__ import annotations

import getpass
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from b_ops.collect.lingxing import LingxingClient, extract_data
from b_ops.collect.transport import content_object, unpack_rpc


def main():
    key = os.getenv("LINGXING_MCP_KEY") or getpass.getpass("Lingxing MCP key: ")
    client = LingxingClient("https://openmcp.lingxing.com/mcp-servers/lingxing-mcp", key)
    del key
    for tool in ("advertising_add_negative_keywords", "advertising_add_negative_targets",
                 "post_targets", "post_targets_sp", "advertising_sp_add_keywords"):
        try:
            response = content_object(unpack_rpc(client.transport.post("tools/call", {
                "name": "search", "arguments": {"toolId": tool}})))
            if response.get("code") != 1:
                data = {"tool": tool, "code": response.get("code"), "message": str(response.get("msg") or "")[:120]}
            else:
                definition = extract_data(response)
                schema = definition.get("inputSchema") or {}
                data = {"tool": tool, "toolType": definition.get("toolType"),
                        "required": schema.get("required"),
                        "fields": sorted((schema.get("properties") or {}).keys()),
                        "item_required": ((schema.get("properties") or {}).get("keywords") or {}).get("items", {}).get("required")}
        except Exception as exc:
            data = {"tool": tool, "error_type": type(exc).__name__, "message": str(exc)[:90]}
        print(json.dumps(data, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
