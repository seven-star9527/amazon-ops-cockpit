from b_ops.diagnose.ads import diagnose_search_terms
from b_ops.collect.refresh import _normalize_search


def row(query, **overrides):
    base = {"profile_id": "p1", "sponsored_type": "sp", "campaign_id": "c1", "ad_group_id": "g1",
            "query": query, "target_match_type": "broad", "clicks": 0, "orders": 0,
            "spends": 0, "sales": 0, "related_asins": ["B012345678"], "record_id": "r1"}
    return {**base, **overrides}


def test_same_query_across_targets_one_negative_action_and_shared_asins():
    rows = [row("blue scissors", clicks=6, spends=4, record_id="a", related_asins=["B012345678", "B098765432"]),
            row("blue scissors", clicks=6, spends=4, record_id="b", related_asins=["B012345678", "B098765432"]),
            row("good", clicks=10, spends=20, orders=2, sales=40, record_id="c")]
    actions = diagnose_search_terms(rows)
    bad = next(item for item in actions if item["query"] == "blue scissors")
    assert bad["kind"] == "negative"
    assert bad["clicks"] == 12 and bad["spend"] == 8
    assert bad["affected_asins"] == ["B012345678", "B098765432"]
    assert len(bad["record_ids"]) == 2


def test_exact_candidate_requires_orders_acos_and_absence_of_existing_exact():
    good = row("kids scissors", clicks=20, spends=9, orders=2, sales=50)
    action = next(item for item in diagnose_search_terms([good]) if item["query"] == "kids scissors")
    assert action["kind"] == "exact"
    existing = row("kids scissors", target_match_type="exact", exact_target_exists=True)
    assert all(item["kind"] != "exact" for item in diagnose_search_terms([good, existing]))


def test_unmapped_group_is_never_executable():
    action = diagnose_search_terms([row("bad", clicks=12, spends=12, related_asins=[]),
                                    row("good", clicks=10, spends=10, orders=1, sales=30, related_asins=[])])
    assert all(not item["executable"] for item in action)


def test_negative_source_is_preserved_without_fuzzy_processed_inference():
    normalized = _normalize_search([{'profile_id':'p1','campaign_id':'c1','ad_group_id':'g1',
                                    'query':'bad term','clicks':20,'spends':30,'orders':0,'sales':0,
                                    'st_negative':'广告组精准否定','st_negatives':{'match_type':'精准否定'}}], {})
    assert normalized[0]['st_negatives'] == {'match_type':'精准否定'}
    assert 'exact_negative_exists' not in normalized[0]


def test_sb_exact_is_diagnosed_but_not_claimed_remote_executable():
    item = row('kids scissors', sponsored_type='sb', orders=2, sales=50, spends=10)
    action = diagnose_search_terms([item])[0]
    assert action['kind'] == 'exact'
    assert action['executable'] is False


def test_sb_negative_is_visible_but_writer_does_not_support_it():
    rows=[row('bad phrase',sponsored_type='sb',clicks=12,spends=20),
          row('good',sponsored_type='sb',clicks=10,orders=2,sales=40,spends=10)]
    action=next(item for item in diagnose_search_terms(rows) if item['query']=='bad phrase')
    assert action['kind']=='negative'
    assert action['executable'] is False


def test_sp_exact_uses_actual_cpc_for_review_only_suggestion():
    action = diagnose_search_terms([row('kids scissors',clicks=20,orders=2,sales=50,spends=10,bid=0.62)])[0]
    assert action['suggested_bid'] == 0.5
    assert action['reviewable'] is True
    assert action['executable'] is False
    without = diagnose_search_terms([row('kids scissors',clicks=0,orders=2,sales=50,spends=10)])[0]
    assert without['suggested_bid'] is None
    assert without['reviewable'] is False
