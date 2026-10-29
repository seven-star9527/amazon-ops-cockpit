import pytest

from b_ops.model.identity import product_key, map_profiles


def test_product_key_includes_shop_site_and_child_asin():
    assert product_key("2907", "US", "B012345678") != product_key("5906", "US", "B012345678")


def test_profile_mapping_rejects_ambiguous_shop():
    with pytest.raises(ValueError):
        map_profiles([
            {"profile_id": "p1", "s_id": "2907"},
            {"profile_id": "p1", "s_id": "5906"},
        ])
