"""Bounded read-only competitor seed probe; credentials are never printed or saved."""

from __future__ import annotations

import argparse
import getpass
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from b_ops.collect.sif import SifClient
from b_ops.collect.sif_discovery import discover_competitors, competitor_asin, _profile_summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("asin")
    parser.add_argument("keyword")
    parser.add_argument("--price", type=float)
    parser.add_argument("--root", action="store_true")
    args = parser.parse_args()
    client = SifClient("https://mcp.sif.com/mcp", os.getenv("SIF_MCP_KEY") or getpass.getpass("SIF key: "))
    if args.root:
        result=client.call("market_get_keyword_root_competitors", {
            "keyword_root": args.keyword, "country": "UK", "topN": 10})
        asins=[competitor_asin(row.get("asin")) for row in result.get("competitors") or []]
        asins=[asin for asin in asins if asin]
        profile=client.call("market_get_asin_profile",{"asins":[args.asin.upper(),*asins],"country":"UK"})
        by_asin={competitor_asin(item.get("asin")):_profile_summary(item)
                 for item in profile.get("list") or [] if isinstance(item,dict)}
        print(json.dumps({"seed":args.keyword,"candidates":[{"asin":asin,
            "title":by_asin.get(asin,{}).get("title"),
            "categories":by_asin.get(asin,{}).get("categories"),
            "price":by_asin.get(asin,{}).get("price")} for asin in asins]},ensure_ascii=False))
        return
    rows = discover_competitors(client, site="UK", asin=args.asin, seed=args.keyword,
                                limit=10, price=args.price)
    profiles = client.call("market_get_asin_profile", {
        "asins": [args.asin.upper(), *[row["asin"] for row in rows]], "country": "UK"})
    by_asin = {competitor_asin(item.get("asin")): _profile_summary(item)
               for item in profiles.get("list") or [] if isinstance(item, dict)}
    print(json.dumps({"seed": args.keyword, "candidates": [{"asin": row["asin"],
          "title": by_asin.get(row["asin"], {}).get("title"),
          "categories": by_asin.get(row["asin"], {}).get("categories"),
          "price": by_asin.get(row["asin"], {}).get("price")}
          for row in rows]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
