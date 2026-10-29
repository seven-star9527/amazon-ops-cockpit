"""Attach a separately dated PMC inventory snapshot to the B workbench.

Advertising/Listing source dates remain untouched. This never upgrades a historical
B run into a purportedly fresh advertising run.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path

from b_ops.diagnose.prioritize import prioritize
from b_ops.model.identity import product_key


def _inventory_issue(row: dict) -> dict | None:
    if int(row.get("listingStatus") or 0) != 1:
        return None
    valid_days = (row.get("forecast") or {}).get("effectiveDays") or 0
    gaps = list(row.get("dataGaps") or [])
    if valid_days < 7:
        return {"domain": "inventory", "type": "insufficient_demand", "severity": "gap",
                "title": "库存需求样本不足", "hypothesis": "有效销售样本少于 7 天，暂不把补货量作为可执行建议。",
                "evidence": {"effective_days": valid_days, "as_of": row.get("asOf")},
                "gaps": gaps, "actionability": 0}
    risk = row.get("risk")
    if risk not in {"critical", "warning", "procurement", "overstock"}:
        return None
    title = {"critical": "断货风险待处理", "warning": "发货/货源待复核",
             "procurement": "采购时点待复核", "overstock": "冗余库存待处理"}[risk]
    return {"domain": "inventory", "type": risk,
            "severity": "critical" if risk == "critical" else "high" if risk == "warning" else "medium",
            "title": title,
            "hypothesis": row.get("decision", {}).get("conclusion") or title,
            "evidence": {"stockout_date": row.get("timeline", {}).get("stockoutDate"),
                         "fba_available": row.get("inventoryLayers", {}).get("sellable"),
                         "daily_forecast": row.get("forecast", {}).get("daily"),
                         "as_of": row.get("asOf")},
            "gaps": gaps, "actionability": 1}


def fuse_board(base: dict, inventory: dict) -> dict:
    board = copy.deepcopy(base)
    metadata = inventory.get("metadata") or {}
    as_of = metadata.get("asOf")
    if not as_of or not isinstance(inventory.get("records"), list):
        raise ValueError("dated PMC projection required")
    products = board.get("products") or {}
    by_identity = {(str(p["sid"]), str(p["asin"]).upper()): p for p in products.values()}
    if len(by_identity) != len(products):
        raise ValueError("ambiguous B store-ASIN identity")
    store_site = {str(p["sid"]): str(p["site"]) for p in products.values()}
    matched = 0
    created = 0
    seen = set()
    for row in inventory["records"]:
        sid, asin = str(row.get("storeId") or ""), str(row.get("asin") or "").upper()
        identity = (sid, asin)
        if not sid or not asin or identity in seen or row.get("asOf") != as_of:
            raise ValueError("duplicate, undated or incomplete PMC store-ASIN")
        seen.add(identity)
        product = by_identity.get(identity)
        if product is None:
            site = store_site.get(sid) or str(row.get("store") or "").rsplit("-", 1)[-1].upper()
            if not site or site == str(row.get("store") or "").upper():
                raise ValueError(f"cannot determine site for PMC product {sid}|{asin}")
            key = product_key(sid, site, asin)
            product = {"key": key, "sid": sid, "site": site, "asin": asin,
                       "shop": row.get("store") or sid, "name": row.get("title") or asin,
                       "status": str(row.get("listingStatus") or ""),
                       "status_text": "仅库存批次有记录", "skus": {}, "stock": {}, "weeks": [],
                       "issues": [], "actions": [], "keyword_state": {"terms": [], "sif_state": "not_queried"}}
            products[key] = product
            created += 1
        else:
            matched += 1
        product["inventory_pmc"] = row
        product["issues"] = [issue for issue in product.get("issues", []) if issue.get("domain") != "inventory"]
        issue = _inventory_issue(row)
        if issue:
            product["issues"].append(issue)
        product["issues"] = prioritize(product["issues"])
    board["products"] = products
    board["inventory_batch"] = {"as_of": as_of, "metadata": metadata,
                                "matched_products": matched, "inventory_only_products": created,
                                "base_as_of": base.get("as_of_date"),
                                "mixed_source_dates": as_of != base.get("as_of_date")}
    board.setdefault("coverage", {})["products"] = len(products)
    board["coverage"]["inventory_products"] = len(seen)
    board["coverage"]["inventory_active"] = sum(
        int(p.get("inventory_pmc", {}).get("listingStatus") or 0) == 1 for p in products.values())
    return board


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--eta", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.eta.is_file():
        raise ValueError("ETA workbook missing")
    base = json.loads(args.base.read_text(encoding="utf-8"))
    inventory = json.loads(args.inventory.read_text(encoding="utf-8"))
    board = fuse_board(base, inventory)
    board["inventory_batch"]["eta_sha256"] = hashlib.sha256(args.eta.read_bytes()).hexdigest()
    board["inventory_batch"]["eta_file_mtime"] = args.eta.stat().st_mtime
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(board, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(json.dumps({"as_of": board["inventory_batch"]["as_of"],
                      "matched":board["inventory_batch"]["matched_products"],
                      "inventory_only":board["inventory_batch"]["inventory_only_products"],
                      "total_products":len(board["products"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
