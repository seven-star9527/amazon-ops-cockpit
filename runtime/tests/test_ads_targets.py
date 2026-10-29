from b_ops.collect.ads_targets import (collect_keyword_target_report, normalize_keyword_target,
                                       target_evidence_by_product, collect_targets_by_profile,
                                       collect_campaign_settings, enrich_targets_with_campaigns)


def _target(**changes):
    row = {
        "profile_id": "p1", "sponsored_type": "sp", "campaign_id": "c1",
        "ad_group_id": "g1", "keyword_id": "k1", "keyword_text": "Kids Knife Set",
        "match_type": "exact", "state": "enabled", "campaign_state": "enabled",
        "ad_group_state": "enabled", "bid": None, "default_bid": "0.50",
        "bidding": {"strategy": "legacyForSales", "adjustments": [
            {"predicate": "placementTop", "percentage": 100},
            {"predicate": "placementRestOfSearch", "percentage": 0},
        ]},
        "impressions": "100", "clicks": "10", "spends": "6.00",
        "orders": "2", "sales": "30.00", "is_apply_time": False,
    }
    row.update(changes)
    return row


def test_normalized_target_keeps_group_grain_and_inherited_bid():
    result = normalize_keyword_target(_target(), "p1")
    assert result["target_id"] == "k1"
    assert result["ad_group_id"] == "g1"
    assert result["normalized_keyword"] == "kids knife set"
    assert result["bid"] is None and result["base_bid"] == 0.5
    assert result["bid_source"] == "group_default"
    assert result["placement_adjustments"] == {"placementTop": 100, "placementRestOfSearch": 0}
    assert result["spend"] == 6 and result["orders"] == 2
    assert result["target_state"] == "enabled"


def test_report_skips_summary_and_paginates_without_claiming_complete_target_catalog():
    calls = []
    summary = {"keyword_id": None, "clicks": "1000"}

    class Client:
        def read(self, tool, params):
            calls.append((tool, params["page"]))
            rows = [summary, _target(keyword_id="k1"), _target(keyword_id="k2", keyword_text="second")]
            if params["page"] == 2:
                rows = [summary, _target(keyword_id="k3", keyword_text="third")]
            return {"code": 1, "data": {"code": 1, "data": rows}}

    rows, status = collect_keyword_target_report(Client(), "p1", "2026-09-28", "2026-10-11", page_size=2)
    assert [row["target_id"] for row in rows] == ["k1", "k2", "k3"]
    assert calls == [("ad_campaign_keyword_report", 1), ("ad_campaign_keyword_report", 2)]
    assert status["state"] == "verified_performance"
    assert status["catalog_complete"] is False


def test_report_does_not_invent_zero_click_or_paused_targets_from_missing_rows():
    class Client:
        def read(self, tool, params):
            return {"code": 1, "data": {"code": 1, "data": [{"keyword_id": None}]}}

    rows, status = collect_keyword_target_report(Client(), "p1", "2026-09-28", "2026-10-11")
    assert rows == []
    assert status["catalog_complete"] is False
    assert status["rows"] == 0


def test_campaign_budget_is_joined_only_on_same_profile_and_campaign():
    class Client:
        def read(self, tool, params):
            assert tool == "ad_campaign_report"
            return {"code":1,"data":{"code":1,"data":[
                {"campaign_id":None},
                {"profile_id":"p1","sponsored_type":"sp","campaign_id":"c1",
                 "budget":"30.00","daily_budget":"30.00","budget_type":"daily",
                 "bidding":{"strategy":"legacyForSales","adjustments":[
                     {"predicate":"placementTop","percentage":100}]},
                 "is_apply_time":False},
            ]}}
    settings, status = collect_campaign_settings(Client(), "p1", "2026-09-28", "2026-10-11")
    assert status["state"] == "verified_performance"
    target = normalize_keyword_target(_target(), "p1")
    enriched = enrich_targets_with_campaigns([target, {**target,"profile_id":"p2"}], settings)
    assert enriched[0]["budget"] == 30
    assert enriched[0]["budget_type"] == "daily"
    assert enriched[0]["placement_adjustments"]["placementTop"] == 100
    assert enriched[1]["budget"] is None


def test_campaign_report_counts_all_sponsored_types_but_returns_only_sp():
    """Live Lingxing can ignore the requested SP filter in campaign reports."""
    class Client:
        def read(self, tool, params):
            assert tool == "ad_campaign_report"
            return {"code": 1, "data": {"code": 1, "recordsFiltered": 3, "data": [
                {"campaign_id": None},
                {"profile_id": "p1", "sponsored_type": "sp", "campaign_id": "sp1", "budget": "10"},
                {"profile_id": "p1", "sponsored_type": "hsa", "campaign_id": "sb1", "budget": "20"},
                {"profile_id": "p1", "sponsored_type": "sd", "campaign_id": "sd1", "budget": "30"},
            ]}}

    settings, status = collect_campaign_settings(Client(), "p1", "2026-09-27", "2026-10-10")
    assert [row["campaign_id"] for row in settings] == ["sp1"]
    assert status["state"] == "verified_performance"
    assert status["rows"] == 1
    assert status["reported_total"] == 3


def test_shared_group_target_projects_to_two_children_without_splitting_metrics():
    products = {f"s1|UK|{asin}": {"key": f"s1|UK|{asin}", "sid": "s1", "site": "UK", "asin": asin,
                                   "parent_asin": "B0PARENT01"}
                for asin in ("B012345678", "B098765432")}
    target = normalize_keyword_target(_target(clicks="10", spends="6.00", orders="2"), "p1")
    result = target_evidence_by_product([target], {("p1", "g1"): {"B012345678", "B098765432"}},
                                        {"p1": "s1"}, products)
    for product in products.values():
        matched = result[product["key"]]["kids knife set"][0]
        assert matched["target_id"] == "k1" and matched["clicks"] == 10
        assert matched["affected_asins"] == ["B012345678", "B098765432"]
        assert matched["shared_group"] is True


def test_profile_failure_is_explicit_and_does_not_erase_other_profile_targets():
    class Client:
        def read(self, tool, params):
            if params["profile_ids"] == ["p2"]:
                raise RuntimeError("permission denied")
            return {"code": 1, "data": {"code": 1, "data": [_target()]}}

    rows, statuses = collect_targets_by_profile(Client(), {"p1": "s1", "p2": "s2"},
                                                 "2026-09-28", "2026-10-11")
    assert len(rows) == 1
    assert statuses["p1"]["state"] == "verified_performance"
    assert statuses["p2"] == {"state": "unavailable", "error_type": "RuntimeError",
                              "catalog_complete": False}
