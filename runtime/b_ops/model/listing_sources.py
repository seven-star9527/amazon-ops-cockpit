"""Attach Listing evidence without mixing shops or inventing missing fields."""

from __future__ import annotations

from b_ops.model.snapshot import number


def _reason(value):
    if isinstance(value, dict):
        return (str(value.get("reason") or value.get("name") or "").strip() or None,
                number(value.get("reasonRation") or value.get("ratio")))
    return (str(value).strip() or None, None) if value is not None else (None, None)


def attach_return_analytics(products: dict, rows: list[dict], *, period: list[str]) -> dict:
    """Join Lingxing order analytics by store and child ASIN, never by ASIN alone."""
    index = {(str(p.get("sid")), str(p.get("asin", "")).upper()): p for p in products.values()}
    matched = unmatched = 0
    for row in rows:
        sid = str(row.get("sid") or row.get("s_id") or row.get("storeId") or "")
        asin = str(row.get("asin") or "").strip().upper()
        product = index.get((sid, asin))
        if not product:
            unmatched += 1
            continue
        main_reason, reason_share = _reason(row.get("mainReturnReason"))
        product["return_analysis"] = {
            "rate": number(row.get("curReturnGoodsVolumeRatio")),
            "prior_rate": number(row.get("preReturnGoodsVolumeRatio")),
            "returns": number(row.get("curReturnGoodsCount")),
            "units": number(row.get("curVolume")),
            "main_reason": main_reason,
            "reason_share": reason_share,
            "period": period,
            "source": "analytics_order_analysis_lists",
        }
        matched += 1
    return {"matched": matched, "unmatched": unmatched}
