"""List SIF rank/history capability names and schemas without running data tools."""

import getpass
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from b_ops.collect.sif import SifClient


def main():
    key=os.getenv("SIF_MCP_KEY") or getpass.getpass("SIF MCP key: ")
    client=SifClient(os.getenv("SIF_MCP_URL") or "https://mcp.sif.com/mcp",key)
    del key
    for tool in client.tools():
        name=str(tool.get("name") or "")
        if any(part in name.lower() for part in ("rank","keyword_history","traffic_trend_detail")):
            schema=tool.get("inputSchema") or {}
            print(json.dumps({"name":name,"required":schema.get("required"),
                              "fields":sorted((schema.get("properties") or {}).keys())},ensure_ascii=False))


if __name__=="__main__":
    main()
