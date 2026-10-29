"""Bound one Codex product conversation to one store + child ASIN."""

from __future__ import annotations


def inspect_product(board: dict, sid: str, asin: str, *, domain: str | None = None) -> dict:
    if domain not in {None, "advertising", "inventory", "listing", "keywords"}:
        raise ValueError("unknown product domain")
    matches = [p for p in board.get("products", {}).values()
               if str(p.get("sid")) == str(sid) and str(p.get("asin", "")).upper() == asin.upper()]
    if len(matches) != 1:
        raise ValueError("store + child ASIN must resolve to exactly one product")
    product = matches[0]
    issues = product.get("issues") or []
    actions = product.get("actions") or []
    keywords = (product.get("keyword_state") or {}).get("terms") or []
    if domain in {"advertising", "inventory", "listing"}:
        issues = [item for item in issues if item.get("domain") == domain]
    if domain not in {None, "advertising"}:
        actions = []
    if domain not in {None, "keywords", "advertising"}:
        keywords = []
    return {"run_id": board["run_id"], "fetched_at": board["fetched_at"],
            "identity": {key: product.get(key) for key in ("key", "sid", "site", "asin", "shop", "name", "url", "status")},
            "issues": issues, "actions": actions, "keywords": keywords,
            "weekly_data": product.get("weeks") or [], "stock": product.get("stock") or {},
            "source_status": board.get("status") or {}}
