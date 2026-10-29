from b_ops.collect.refresh import _normalize_search
from b_ops.diagnose.ads import diagnose_search_terms


ASIN = "B012345678"


def term(query, *, group="g1", record="r1", clicks=0, spends=0, orders=0, sales=0, **extra):
    return {
        "profile_id": "p1", "sponsored_type": "sp", "campaign_id": "c1", "ad_group_id": group,
        "campaign_name": "Campaign", "ad_group_name": group, "query": query,
        "target_match_type": "broad", "campaign_state": "enabled", "ad_group_state": "enabled",
        "target_state": "enabled", "record_id": record, "related_asins": [ASIN],
        "clicks": clicks, "spends": spends, "orders": orders, "sales": sales, **extra,
    }


def test_exact_sources_merge_to_one_review_plan_with_actual_cpc_and_destination():
    rows = [
        term("good term", record="a", clicks=10, spends=5, orders=2, sales=30),
        term("GOOD TERM", group="g2", record="b", clicks=20, spends=10, orders=3, sales=50),
    ]
    actions = diagnose_search_terms(rows)
    exact = [item for item in actions if item["kind"] == "exact"]
    assert len(exact) == 1
    assert exact[0]["affected_asins"] == [ASIN]
    assert exact[0]["clicks"] == 30 and exact[0]["spend"] == 15
    assert exact[0]["suggested_bid"] == 0.5
    assert len(exact[0]["source_scopes"]) == 2
    assert exact[0]["ad_group_id"] == "g2"
    assert exact[0]["reviewable"] is True
    assert exact[0]["executable"] is False


def test_current_exact_negative_is_processed_only_for_same_object_and_group():
    raw = [
        term("bad term", clicks=12, spends=15,
             st_negatives=[{"match_type": "已否定", "ng_level": "ad_group"}]),
        term("good", record="r2", clicks=10, spends=8, orders=2, sales=40),
    ]
    links = {("p1", "g1"): {ASIN}}
    normalized = _normalize_search(raw, links)
    bad = next(item for item in diagnose_search_terms(normalized) if item["query"] == "bad term")
    assert bad["kind"] == "negative"
    assert bad["processed_status"] == "already_exact_negative"
    assert bad["reviewable"] is False and bad["executable"] is False
    other = raw[0].copy()
    other["st_negatives"] = [{"keyword": "unrelated", "match_type": "精准否定", "ng_level": "ad_group"}]
    normalized = _normalize_search([other, raw[1]], links)
    bad = next(item for item in diagnose_search_terms(normalized) if item["query"] == "bad term")
    assert bad["processed_status"] == ""


def test_running_exact_elsewhere_blocks_new_exact_plan_but_paused_does_not():
    source = term("good term", clicks=20, spends=10, orders=2, sales=50)
    running = term("good term", group="g2", record="existing", target_match_type="exact",
                   match_type="exact", targeting_text="good term", clicks=2)
    actions = diagnose_search_terms([source, running])
    exact = next(item for item in actions if item["kind"] == "exact")
    assert exact["processed_status"] == "already_exact_running"
    assert exact["reviewable"] is False
    matches = exact["existing_exact_matches"]
    assert len(matches) == 1
    assert matches[0]["ad_group_id"] == "g2"
    assert matches[0]["clicks"] == 2
    running["target_state"] = "paused"
    exact = next(item for item in diagnose_search_terms([source, running]) if item["kind"] == "exact")
    assert exact["processed_status"] == ""


def test_paused_exact_target_in_same_group_does_not_suppress_new_candidate():
    source = term("good term", clicks=20, spends=10, orders=2, sales=50)
    stopped = term("good term", record="paused-exact", target_match_type="exact",
                   match_type="exact", targeting_text="good term", target_state="paused")
    exact = next(item for item in diagnose_search_terms([source, stopped]) if item["kind"] == "exact")
    assert exact["reviewable"] is True


def test_negative_uses_reference_cpa_and_never_promotes_sb_to_write():
    good = term("good", clicks=10, spends=8, orders=2, sales=40)
    bad = term("bad", record="b", clicks=12, spends=5)
    actions = diagnose_search_terms([good, bad])
    assert not any(item["kind"] == "negative" for item in actions)
    bad["spends"] = 8
    negative = next(item for item in diagnose_search_terms([good, bad]) if item["kind"] == "negative")
    assert negative["reference_cpa"] == 6
    assert negative["executable"] is True
    good["sponsored_type"] = bad["sponsored_type"] = "sb"
    negative = next(item for item in diagnose_search_terms([good, bad]) if item["kind"] == "negative")
    assert negative["executable"] is False


def test_unmapped_and_explicitly_paused_source_cannot_enter_review():
    rows = [term("bad", clicks=12, spends=10, related_asins=[]),
            term("good", record="r2", clicks=10, spends=5, orders=1, sales=30, related_asins=[])]
    assert all(not item["reviewable"] for item in diagnose_search_terms(rows))
    rows[0]["related_asins"] = rows[1]["related_asins"] = [ASIN]
    rows[0]["campaign_state"] = "paused"
    assert all(item["query"] != "bad" or item["kind"] == "observe" for item in diagnose_search_terms(rows))
