from b_ops.diagnose.ads import diagnose_search_terms
from b_ops.diagnose.ads_decisions import (group_scoped_actions, target_bid_reviews,
                                           summarize_rank_evidence, reconcile_exact_targets)


def row(group, record, *, asins, query="kids knife set", orders=2, clicks=20, spend=10, sales=50):
    return {"profile_id": "p1", "sponsored_type": "sp", "campaign_id": "c1", "ad_group_id": group,
            "campaign_name": "Campaign", "ad_group_name": group, "query": query,
            "target_match_type": "broad", "campaign_state": "enabled", "ad_group_state": "enabled",
            "target_state": "enabled", "record_id": record, "related_asins": asins,
            "clicks": clicks, "spends": spend, "orders": orders, "sales": sales}


def products():
    return {
        "s1|UK|B0CHILD001": {"key":"s1|UK|B0CHILD001", "sid":"s1", "site":"UK",
                               "asin":"B0CHILD001", "parent_asin":"B0PARENT01"},
        "s1|UK|B0CHILD002": {"key":"s1|UK|B0CHILD002", "sid":"s1", "site":"UK",
                               "asin":"B0CHILD002", "parent_asin":"B0PARENT01"},
    }


def test_exact_specialist_sources_become_one_action_per_ad_group_not_per_child():
    source = diagnose_search_terms([
        row("g1", "a", asins=["B0CHILD001", "B0CHILD002"]),
        row("g2", "b", asins=["B0CHILD001", "B0CHILD002"]),
    ])
    actions = group_scoped_actions(source, products(), {"p1":"s1"})
    exact = [a for a in actions if a["kind"] == "exact"]
    assert len(exact) == 2
    assert {a["ad_group_id"] for a in exact} == {"g1", "g2"}
    assert all(a["affected_asins"] == ["B0CHILD001", "B0CHILD002"] for a in exact)
    assert all(a["reviewable"] and not a["executable"] for a in exact)
    assert all(a["exact_plan"]["target_required"] for a in exact)
    assert len({a["action_key"] for a in exact}) == 2


def test_cross_parent_shared_group_stays_blocked():
    source = diagnose_search_terms([row("g1", "a", asins=["B0CHILD001", "B0OTHER001"])])
    catalog = products()
    catalog["s1|UK|B0OTHER001"] = {"key":"s1|UK|B0OTHER001", "sid":"s1", "site":"UK",
                                    "asin":"B0OTHER001", "parent_asin":"B0OTHERPAR"}
    exact = next(a for a in group_scoped_actions(source, catalog, {"p1":"s1"}) if a["kind"] == "exact")
    assert not exact["reviewable"]
    assert exact["blocked_reason"] == "cross_parent_shared_group"


def test_positive_exact_target_report_prevents_duplicate_addition():
    action=group_scoped_actions(diagnose_search_terms([
        row("g1","a",asins=["B0CHILD001","B0CHILD002"])]), products(), {"p1":"s1"})[0]
    target={"profile_id":"p1","campaign_id":"c2","ad_group_id":"g2","target_id":"t1",
            "normalized_keyword":"kids knife set","match_type":"exact","target_state":"enabled",
            "campaign_state":"enabled","ad_group_state":"enabled"}
    result=reconcile_exact_targets([action],[target],{("p1","g2"):{"B0CHILD001","B0CHILD002"}},
                                   products(),{"p1":"s1"}, target_status={"p1":{"state":"verified_performance"}})
    assert result[0]["processed_status"] == "already_exact_running"
    assert result[0]["reviewable"] is False
    assert result[0]["target_check"] == "active_exact_verified"


def test_missing_report_target_stays_unknown_and_paused_target_is_not_new():
    action=group_scoped_actions(diagnose_search_terms([
        row("g1","a",asins=["B0CHILD001"])]), products(), {"p1":"s1"})[0]
    unknown=reconcile_exact_targets([action],[],{},products(),{"p1":"s1"},
                                    target_status={"p1":{"state":"verified_performance","catalog_complete":False}})[0]
    assert unknown["target_check"] == "unknown_incomplete_catalog"
    assert unknown["reviewable"] is True and unknown["executable"] is False
    paused={"profile_id":"p1","campaign_id":"c2","ad_group_id":"g2","target_id":"t1",
            "normalized_keyword":"kids knife set","match_type":"exact","target_state":"paused",
            "campaign_state":"enabled","ad_group_state":"enabled"}
    result=reconcile_exact_targets([action],[paused],{("p1","g2"):{"B0CHILD001"}},
                                   products(),{"p1":"s1"},target_status={"p1":{"state":"verified_performance"}})[0]
    assert result["target_check"] == "paused_exact_verified"
    assert result["reviewable"] is False


def test_bid_review_requires_real_target_identity_and_does_not_invent_numeric_bid():
    target = {"profile_id":"p1", "campaign_id":"c1", "ad_group_id":"g1", "target_id":"t1",
              "normalized_keyword":"kids knife set", "keyword":"kids knife set", "match_type":"exact",
              "target_state":"enabled", "campaign_state":"enabled", "ad_group_state":"enabled",
              "bid":.5, "base_bid":.5, "bidding_strategy":"legacyForSales",
              "placement_adjustments":{"placementTop":100}, "budget":None,
              "clicks":20, "orders":2, "spend":10, "sales":50}
    reviews = target_bid_reviews([target], products(), {("p1","g1"):{"B0CHILD001","B0CHILD002"}},
                                 {"p1":"s1"}, rank_by_product={})
    assert len(reviews) == 1
    assert reviews[0]["affected_asins"] == ["B0CHILD001", "B0CHILD002"]
    assert reviews[0]["target_id"] == "t1"
    assert reviews[0]["suggested_bid"] is None
    assert reviews[0]["direction"] == "needs_rank_and_budget"
    assert reviews[0]["reviewable"] is False


def test_rank_summary_keeps_absolute_rank_and_page_position_separate():
    observations = ([{"observed_date":f"2026-10-{day:02d}","channel":"natural",
                      "state":"absolute_rank","rank":30,"display":None} for day in range(1,13)] +
                    [{"observed_date":f"2026-10-{day:02d}","channel":"advertising",
                      "state":"reported_position","rank":None,"display":"P2#4"} for day in range(1,13)])
    summary = summarize_rank_evidence(observations, ["2026-10-01", "2026-10-14"])
    assert summary["state"] == "verified"
    assert summary["natural_latest"] == 30
    assert summary["advertising_latest"] is None
    assert summary["advertising_page_latest"] == 2


def test_rank_bid_evidence_requires_both_weeks_not_ten_days_in_one_week():
    observations=[{"observed_date":f"2026-10-{day:02d}","channel":"natural",
                   "state":"absolute_rank","rank":20} for day in range(1,11)]
    summary=summarize_rank_evidence(observations,["2026-10-01","2026-10-14"])
    assert summary["state"] == "insufficient_days"
    assert summary["week_days"] == [7,3]


def test_bid_rank_requires_each_channel_in_each_week_not_union_of_sparse_channels():
    observations = ([{"observed_date":f"2026-10-{day:02d}","channel":"natural",
                      "state":"absolute_rank","rank":20} for day in range(1,8)] +
                    [{"observed_date":f"2026-10-{day:02d}","channel":"advertising",
                      "state":"reported_position","display":"P2#4"} for day in range(8,15)])
    summary = summarize_rank_evidence(observations, ["2026-10-01", "2026-10-14"])
    assert summary["week_days"] == [7,7]
    assert summary["natural_week_days"] == [7,0]
    assert summary["advertising_week_days"] == [0,7]
    assert summary["state"] == "insufficient_days"


def test_bid_direction_uses_target_performance_with_external_rank_context_only():
    target = {"profile_id":"p1", "campaign_id":"c1", "ad_group_id":"g1", "target_id":"t1",
              "normalized_keyword":"kids knife set", "keyword":"kids knife set", "match_type":"exact",
              "target_state":"enabled", "campaign_state":"enabled", "ad_group_state":"enabled",
              "bid":.5, "base_bid":.5, "bidding_strategy":"legacyForSales",
              "placement_adjustments":{"placementTop":100}, "budget":30, "is_apply_time":False,
              "clicks":20, "orders":2, "spend":10, "sales":50}
    key=("s1|UK|B0CHILD001","kids knife set")
    signal={"state":"verified", "observed_days":11, "natural_latest":30,
            "advertising_latest":None, "advertising_page_latest":2}
    rank={key:signal,("s1|UK|B0CHILD002","kids knife set"):signal}
    reviews=target_bid_reviews([target], products(), {("p1","g1"):{"B0CHILD001","B0CHILD002"}},
                               {"p1":"s1"},rank)
    assert reviews[0]["direction"] == "consider_raise"
    assert reviews[0]["reviewable"] is True
    assert reviews[0]["suggested_bid"] is None
    assert reviews[0]["effective_bid_ceiling"] == 1.0
    assert reviews[0]["rank_evidence"]["attribution"] == "asin_external_not_target"


def test_zero_budget_cannot_be_reviewed_as_a_bid_increase():
    target = {"profile_id":"p1", "campaign_id":"c1", "ad_group_id":"g1", "target_id":"t1",
              "normalized_keyword":"kids knife set", "keyword":"kids knife set", "match_type":"exact",
              "target_state":"enabled", "campaign_state":"enabled", "ad_group_state":"enabled",
              "base_bid":.5, "bidding_strategy":"legacyForSales", "placement_adjustments":{},
              "budget":0, "is_apply_time":False, "clicks":20, "orders":2, "spend":10, "sales":50}
    signal={"state":"verified", "natural_latest":30,"advertising_page_latest":2,"observed_days":12}
    rank={(f"s1|UK|{asin}","kids knife set"):signal for asin in ("B0CHILD001","B0CHILD002")}
    action=target_bid_reviews([target],products(),{("p1","g1"):{"B0CHILD001","B0CHILD002"}},
                              {"p1":"s1"},rank)[0]
    assert action["direction"] == "needs_budget"
    assert action["reviewable"] is False


def test_campaign_budget_utilization_proxy_is_warning_not_a_hard_bid_gate():
    target = {"profile_id":"p1", "campaign_id":"c1", "ad_group_id":"g1", "target_id":"t1",
              "normalized_keyword":"kids knife set", "keyword":"kids knife set", "match_type":"exact",
              "target_state":"enabled", "campaign_state":"enabled", "ad_group_state":"enabled",
              "base_bid":.5, "bidding_strategy":"legacyForSales", "placement_adjustments":{},
              "budget":30, "budget_type":"daily", "campaign_spend":390,
              "is_apply_time":False, "clicks":20, "orders":2, "spend":10, "sales":50}
    signal={"state":"verified", "natural_latest":30,"advertising_page_latest":2,"observed_days":12}
    rank={(f"s1|UK|{asin}","kids knife set"):signal for asin in ("B0CHILD001","B0CHILD002")}
    action=target_bid_reviews([target],products(),{("p1","g1"):{"B0CHILD001","B0CHILD002"}},
                              {"p1":"s1"},rank)[0]
    assert action["direction"] == "consider_raise"
    assert action["reviewable"] is True
    assert action["budget_utilization_proxy"] > .9


def test_shared_group_bid_lists_missing_variant_without_hiding_group_level_review():
    target={"profile_id":"p1","campaign_id":"c1","ad_group_id":"g1","target_id":"t1",
            "normalized_keyword":"kids knife set","keyword":"kids knife set","match_type":"exact",
            "target_state":"enabled","campaign_state":"enabled","ad_group_state":"enabled",
            "base_bid":.5,"bidding_strategy":"legacyForSales","placement_adjustments":{},
            "budget":30,"is_apply_time":False,"clicks":20,"orders":2,"spend":10,"sales":50}
    rank={("s1|UK|B0CHILD001","kids knife set"):{"state":"verified","natural_latest":30,
          "advertising_page_latest":2,"observed_days":11}}
    action=target_bid_reviews([target],products(),{("p1","g1"):{"B0CHILD001","B0CHILD002"}},
                              {"p1":"s1"},rank)[0]
    assert action["direction"] == "consider_raise"
    assert action["reviewable"] is True
    assert action["rank_evidence"]["children"]["B0CHILD002"] is None


def test_bid_raise_stays_blocked_when_another_variant_is_already_strong_in_ads():
    target={"profile_id":"p1","campaign_id":"c1","ad_group_id":"g1","target_id":"t1",
            "normalized_keyword":"kids knife set","keyword":"kids knife set","match_type":"exact",
            "target_state":"enabled","campaign_state":"enabled","ad_group_state":"enabled",
            "base_bid":.5,"budget":30,"clicks":20,"orders":3,"spend":10,"sales":80}
    rank={("s1|UK|B0CHILD001","kids knife set"):{"state":"insufficient_days",
          "advertising_week_days":[1,3],"advertising_latest":23},
          ("s1|UK|B0CHILD002","kids knife set"):{"state":"insufficient_days",
          "advertising_week_days":[2,2],"advertising_latest":4}}
    action=target_bid_reviews([target],products(),{("p1","g1"):{"B0CHILD001","B0CHILD002"}},
                              {"p1":"s1"},rank)[0]
    assert action["direction"] == "variant_rank_conflict"
    assert action["reviewable"] is False


def test_group_negative_blocks_bid_raise_for_same_word_and_target():
    target={"profile_id":"p1","campaign_id":"c1","ad_group_id":"g1","target_id":"t1",
            "normalized_keyword":"kids knife set","keyword":"kids knife set","match_type":"exact",
            "target_state":"enabled","campaign_state":"enabled","ad_group_state":"enabled",
            "base_bid":.5,"bidding_strategy":"legacyForSales","placement_adjustments":{},
            "budget":30,"is_apply_time":False,"clicks":20,"orders":2,"spend":10,"sales":50}
    signal={"state":"verified","natural_latest":30,"advertising_page_latest":2,"observed_days":12}
    rank={(f"s1|UK|{asin}","kids knife set"):signal for asin in ("B0CHILD001","B0CHILD002")}
    negative={"kind":"negative","profile_id":"p1","campaign_id":"c1","ad_group_id":"g1",
              "normalized_keyword":"kids knife set","reviewable":True}
    action=target_bid_reviews([target],products(),{("p1","g1"):{"B0CHILD001","B0CHILD002"}},
                              {"p1":"s1"},rank,negative_actions=[negative])[0]
    assert action["direction"] == "conflict_negative"
    assert action["reviewable"] is False


def test_bid_lower_is_reviewable_with_directional_rank_and_dynamic_strategy():
    target={"profile_id":"p1","campaign_id":"c1","ad_group_id":"g1","target_id":"t1",
            "normalized_keyword":"kids knife set","keyword":"kids knife set","match_type":"exact",
            "target_state":"enabled","campaign_state":"enabled","ad_group_state":"enabled",
            "base_bid":.5,"bidding_strategy":"autoForSales","budget":30,"is_apply_time":False,
            "clicks":20,"orders":2,"spend":40,"sales":80}
    rank={("s1|UK|B0CHILD001","kids knife set"):{"state":"insufficient_days",
          "observed_days":4,"natural_week_days":[0,0],"advertising_week_days":[1,3],
          "advertising_latest":17}}
    action=target_bid_reviews([target],products(),{("p1","g1"):{"B0CHILD001","B0CHILD002"}},
                              {"p1":"s1"},rank)[0]
    assert action["direction"] == "consider_lower"
    assert action["reviewable"] is True
    assert action["executable"] is False
    assert action["effective_bid_ceiling"] is None
    assert action["rank_evidence"]["review_basis"] == "directional"
    assert action["rank_evidence"]["children"]["B0CHILD002"] is None


def test_bid_raise_uses_weak_ad_position_and_target_conversion_without_natural_rank():
    target={"profile_id":"p1","campaign_id":"c1","ad_group_id":"g1","target_id":"t1",
            "normalized_keyword":"kids knife set","keyword":"kids knife set","match_type":"exact",
            "target_state":"enabled","campaign_state":"enabled","ad_group_state":"enabled",
            "base_bid":.5,"bidding_strategy":"legacyForSales","budget":30,"is_apply_time":False,
            "clicks":18,"orders":5,"spend":9,"sales":73}
    rank={("s1|UK|B0CHILD001","kids knife set"):{"state":"insufficient_days",
          "observed_days":9,"natural_week_days":[0,0],"advertising_week_days":[4,5],
          "advertising_latest":22}}
    action=target_bid_reviews([target],products(),{("p1","g1"):{"B0CHILD001"}},
                              {"p1":"s1"},rank)[0]
    assert action["direction"] == "consider_raise"
    assert action["reviewable"] is True
    assert action["suggested_bid"] is None


def test_one_day_rank_does_not_create_a_bid_review():
    target={"profile_id":"p1","campaign_id":"c1","ad_group_id":"g1","target_id":"t1",
            "normalized_keyword":"kids knife set","keyword":"kids knife set","match_type":"exact",
            "target_state":"enabled","campaign_state":"enabled","ad_group_state":"enabled",
            "base_bid":.5,"budget":30,"clicks":20,"orders":0,"spend":20,"sales":0}
    rank={("s1|UK|B0CHILD001","kids knife set"):{"state":"insufficient_days",
          "observed_days":1,"natural_week_days":[0,0],"advertising_week_days":[0,1],
          "advertising_latest":25}}
    action=target_bid_reviews([target],products(),{("p1","g1"):{"B0CHILD001"}},
                              {"p1":"s1"},rank)[0]
    assert action["direction"] == "needs_rank"
    assert action["reviewable"] is False
