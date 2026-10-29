"""Join Lingxing buyer queries to SIF words without assigning shared-group sales to an ASIN."""

from __future__ import annotations

from collections import defaultdict

from b_ops.model.snapshot import number
from b_ops.model.storage import normalize_keyword


def build_keyword_evidence(rows: list[dict], profile_to_sid: dict,
                           products: dict[str, dict]) -> dict[str, dict[str, dict]]:
    by_product = {(str(p["sid"]), str(p["asin"]).upper()): key for key, p in products.items()}
    staged = defaultdict(lambda: defaultdict(list))
    seen = set()
    for row in rows:
        sid = profile_to_sid.get(str(row.get("profile_id") or ""))
        normalized = normalize_keyword(str(row.get("query") or ""))
        if not sid or not normalized:
            continue
        asins = sorted({str(asin).upper() for asin in row.get("related_asins") or [] if asin})
        if not asins:
            continue
        identity = (str(row.get("profile_id")), str(row.get("campaign_id")),
                    str(row.get("ad_group_id")), str(row.get("record_id")), normalized)
        if identity in seen:
            continue
        seen.add(identity)
        source = {"record_id": str(row.get("record_id") or ""),
                  "campaign_id": str(row.get("campaign_id") or ""),
                  "campaign_name": str(row.get("campaign_name") or ""),
                  "ad_group_id": str(row.get("ad_group_id") or ""),
                  "ad_group_name": str(row.get("ad_group_name") or ""),
                  "match_type": str(row.get("target_match_type") or ""),
                  "clicks": number(row.get("clicks")), "spend": number(row.get("spends")),
                  "orders": number(row.get("orders")), "sales": number(row.get("sales")),
                  "affected_asins": asins, "shared_group": len(asins) > 1}
        for asin in asins:
            key = by_product.get((str(sid), asin))
            if key:
                staged[key][normalized].append(source)
    result = {}
    for product_key, terms in staged.items():
        result[product_key] = {}
        for normalized, sources in terms.items():
            def total(field):
                values = [source[field] for source in sources]
                return sum(values) if all(value is not None for value in values) else None
            result[product_key][normalized] = {
                "normalized": normalized, "query": normalized,
                "clicks": total("clicks"), "spend": total("spend"),
                "orders": total("orders"), "sales": total("sales"),
                "match_types": sorted({source["match_type"] for source in sources if source["match_type"]}),
                "attribution": "shared_ad_group" if any(source["shared_group"] for source in sources)
                               else "exclusive_group",
                "sources": sources,
            }
    return result
