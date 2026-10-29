"""Read one ASIN's SIF traffic detail and print only shape/sample field names."""

import getpass
import json
import os
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from b_ops.collect.sif import SifClient


def describe(value,depth=0):
    if depth>3:return type(value).__name__
    if isinstance(value,list):return {"count":len(value),"first":describe(value[0],depth+1) if value else None}
    if isinstance(value,dict):return {name:describe(item,depth+1) for name,item in list(value.items())[:25]}
    return type(value).__name__


def main():
    key=os.getenv("SIF_MCP_KEY") or getpass.getpass("SIF MCP key: ")
    client=SifClient(os.getenv("SIF_MCP_URL") or "https://mcp.sif.com/mcp",key)
    del key
    result=client.call("ops_get_asin_traffic_trend_detail",{
        "asin":"B0F28S5DXN","country":"UK","endDay":"2026-10-12","granularity":"day",
        "desc":True,"pageNum":1,"pageSize":20})
    print(json.dumps(describe(result),ensure_ascii=False,indent=2))


if __name__=="__main__":main()
