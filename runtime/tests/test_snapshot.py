import pytest

from b_ops.model.snapshot import normalize_products


def _raw():
    return {
        "shops": [{"s_id": 2, "name": "店铺A", "country_code": "US", "currency": "USD"}],
        "listings": [
            {"store_id": 2, "asin": "B012345678", "msku": "sku1", "local_name": "中文品名", "item_name": "English Title", "status": 1, "afn_fulfillable_quantity": 10, "afn_inbound_shipped_quantity": 5, "stars": 4.1, "reviews_num": 20},
            {"store_id": 2, "asin": "B012345678", "msku": "sku2", "local_name": "中文品名", "status": 1, "afn_fulfillable_quantity": 3, "afn_inbound_shipped_quantity": 2},
        ],
        "performance": [
            {"_requested_sid": "2", "_week_start": "2026-10-05", "asin": "B012345678", "sids": ["2"], "rdate": "2026-10-05~2026-10-11", "volume": 7, "amount": 70, "sessions_total": 100, "clicks": 25, "order_items": 7, "spend": 12},
        ],
    }


def test_normalize_product_preserves_cn_name_sku_stock_and_missing_week():
    weeks = [{"label": "W40", "start": "2026-09-28", "end": "2026-10-04"}, {"label": "W41", "start": "2026-10-05", "end": "2026-10-11"}]
    products, gaps = normalize_products(_raw(), weeks)
    assert len(products) == 1
    product = products["2|US|B012345678"]
    assert product["name"] == "中文品名" and product["english_title"] == "English Title"
    assert product["stock"]["sellable"] is None
    assert product["stock"]["listing_sellable"] == 13
    assert product["stock"]["source"] == "listing_only_unverified"
    assert product["stock"]["inbound_shipped"] == 7
    assert product["weeks"][0]["units"] is None
    assert product["weeks"][1]["natural_sessions_est"] == 75
    assert gaps["unmapped_performance_rows"] == 0


def test_normalize_product_preserves_parent_asin_for_shared_group_context():
    raw = _raw()
    for row in raw["listings"]:
        row["parent_asin"] = "B0PARENT01"
    product = normalize_products(raw, [{"label": "W41", "start": "2026-10-05", "end": "2026-10-11"}])[0]["2|US|B012345678"]
    assert product["parent_asin"] == "B0PARENT01"


def test_wrong_week_and_store_response_is_rejected():
    raw = _raw()
    raw["performance"][0]["sids"] = ["other"]
    with pytest.raises(ValueError, match="store"):
        normalize_products(raw, [{"label": "W41", "start": "2026-10-05", "end": "2026-10-11"}])


def test_fba_stock_age_and_excess_are_mapped_to_same_shop_asin():
    raw = _raw()
    raw['stock'] = [{"sid":2,"asin":"B012345678","afn_fulfillable_quantity":8,
                     "real_transit_quantity":5,"estimated_excess_quantity":4,
                     "inv_age_181_to_270_days":2,"inv_age_271_to_365_days":1,"inv_age_365_plus_days":1}]
    products, _ = normalize_products(raw,[{"label":"W41","start":"2026-10-05","end":"2026-10-11"}])
    stock = products['2|US|B012345678']['stock']
    assert stock['sellable'] == 8
    assert stock['listing_sellable'] == 13
    assert stock['age_181_plus'] == 4
    assert stock['excess_estimate'] == 4
