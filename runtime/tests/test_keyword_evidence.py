from b_ops.diagnose.keyword_evidence import build_keyword_evidence


def test_internal_search_term_matches_sif_word_without_becoming_core():
    products = {
        "s1|US|B012345678": {"key": "s1|US|B012345678", "sid": "s1", "asin": "B012345678"}}
    rows = [{"profile_id": "p1", "campaign_id": "c1", "campaign_name": "Campaign",
             "ad_group_id": "g1", "ad_group_name": "Group", "query": " Kids  Scissors ",
             "target_match_type": "broad", "clicks": 11, "spends": 8, "orders": 2,
             "sales": 30, "record_id": "r1", "related_asins": ["B012345678"]}]
    result = build_keyword_evidence(rows, {"p1": "s1"}, products)
    item = result["s1|US|B012345678"]["kids scissors"]
    assert item["clicks"] == 11 and item["orders"] == 2
    assert item["match_types"] == ["broad"]
    assert item["sources"][0]["record_id"] == "r1"
    assert item["attribution"] == "exclusive_group"


def test_shared_group_is_exposed_not_claimed_as_asin_attributed():
    products = {f"s1|US|{asin}": {"key": f"s1|US|{asin}", "sid": "s1", "asin": asin}
                for asin in ("B012345678", "B098765432")}
    rows = [{"profile_id": "p1", "campaign_id": "c1", "ad_group_id": "g1",
             "query": "kids scissors", "clicks": 11, "spends": 8, "orders": 2,
             "sales": 30, "record_id": "r1", "related_asins": ["B012345678", "B098765432"]}]
    result = build_keyword_evidence(rows, {"p1": "s1"}, products)
    for product in products.values():
        item = result[product["key"]]["kids scissors"]
        assert item["attribution"] == "shared_ad_group"
        assert item["sources"][0]["affected_asins"] == ["B012345678", "B098765432"]
