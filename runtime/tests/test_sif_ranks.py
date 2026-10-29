from b_ops.collect.sif_ranks import parse_campaign_rank_history, recent_rank_windows, collect_rank_history, current_rank_fields
from b_ops.collect.sif_single import query_single_sif
from b_ops.collect.replay import ReplayMissing
from b_ops.model.storage import StateStore


def payload(start, natural, advertising):
    from datetime import date, timedelta
    days = [(date.fromisoformat(start) + timedelta(days=i)).isoformat() for i in range(7)]
    return {"items": [{
        "keyword": "kids scissors",
        "naturalRankHistory": {"dates": days, "variants": [
            {"asin": "B012345678", "points": [{"rank": value, "rankLabel": f"p1,{value}/48"} for value in natural]},
            {"asin": "B099999999", "points": [{"rank": 1} for _ in days]},
        ]},
        "exposedAdGroups": [{"adGroupId": "g1", "variants": [{"asin": "B012345678"}]}],
        "adRankHistory": {"dates": days, "adGroups": [
            {"adGroupId": "g1", "points": [{"rank": value, "rankLabel": f"p1,{value}/12"} if value else None
                                       for value in advertising]},
            {"adGroupId": "other", "points": [{"rank": 1} for _ in days]},
        ]},
    }]}


def test_rank_parser_keeps_target_and_real_dates_only():
    rows = parse_campaign_rank_history(payload("2026-10-01", [12, 11, 10, 9, 8, 7, 6],
                                               [9, 8, 0, 7, 6, 5, 4]), "B012345678", "c1")
    natural = [r for r in rows if r["channel"] == "natural"]
    advertising = [r for r in rows if r["channel"] == "advertising"]
    assert len(natural) == 7 and len(advertising) == 6
    assert natural[0]["rank"] == 12 and natural[-1]["rank"] == 6
    assert all(r["rank"] != 1 for r in rows)
    assert advertising[0]["source_group"] == "g1"


def test_two_adjacent_windows_cover_fourteen_days_without_backfill():
    windows = recent_rank_windows("2026-10-13")
    assert windows == [("2026-09-27", "2026-10-03"), ("2026-10-04", "2026-10-10")]
    first = parse_campaign_rank_history(payload(windows[0][0], [10]*7, [None]*7), "B012345678", "c1")
    second = parse_campaign_rank_history(payload(windows[1][0], [9]*7, [None]*7), "B012345678", "c1")
    assert len([r for r in first + second if r["channel"] == "natural"]) == 14
    assert not any(r["channel"] == "advertising" for r in first + second)


def test_rank_parser_accepts_sif_linked_asin_and_keeps_dated_points():
    source = payload("2026-10-04", [12, 11, 10, 9, 8, 7, 6], [9, 8, 0, 7, 6, 5, 4])
    source["items"][0]["naturalRankHistory"]["variants"][0]["asin"] = (
        "[B012345678](https://www.amazon.co.uk/dp/B012345678)")
    source["items"][0]["exposedAdGroups"][0]["variants"][0]["asin"] = (
        "[B012345678](https://www.amazon.co.uk/dp/B012345678)")
    rows = parse_campaign_rank_history(source, "B012345678", "C1")
    assert len([row for row in rows if row["channel"] == "natural"]) == 7
    assert len([row for row in rows if row["channel"] == "advertising"]) == 6


def test_rank_collector_requests_two_real_windows_for_a_tracked_word():
    calls = []
    windows = recent_rank_windows("2026-10-13")

    class FakeSif:
        def call(self, tool, params):
            calls.append((tool, params))
            if tool == "ads_get_asin_campaign_contribution_overview":
                return {"campaigns": [{"campaign_display_id": "C1", "contribution_score": 9}]}
            return payload(params["start_date"], [10]*7, [9]*7)

    result = collect_rank_history(FakeSif(), "US", "B012345678", "2026-10-13",
                                  {"kids scissors"}, campaign_limit=1)
    assert result["state"] == "verified"
    assert len(result["observations"]) == 28
    assert [call[1]["start_date"] for call in calls[1:]] == [windows[1][0], windows[0][0]]


def test_rank_collector_probes_sp_campaigns_and_selects_by_real_core_rank_coverage():
    calls = []

    class FakeSif:
        def call(self, tool, params):
            calls.append((tool, params))
            if tool == "ads_get_asin_campaign_contribution_overview":
                return {"campaigns": [
                    {"campaign_display_id": "SBV", "ad_type": "SBV", "contribution_score": 900},
                    {"campaign_display_id": "SP1", "ad_type": "SP", "contribution_score": 20},
                    {"campaign_display_id": "SP2", "ad_type": "SP", "contribution_score": 10},
                ]}
            keyword = "kids scissors" if params["campaignId"] == "SP1" else "toddler knife"
            response = payload(params["start_date"], [8]*7, [5]*7)
            response["items"][0]["keyword"] = keyword
            response["items"][0]["naturalRankHistory"]["variants"][0]["asin"] = (
                "[B012345678](https://www.amazon.com/dp/B012345678)")
            response["items"][0]["exposedAdGroups"][0]["variants"][0]["asin"] = (
                "[B012345678](https://www.amazon.com/dp/B012345678)")
            return response

    result = collect_rank_history(FakeSif(), "US", "B012345678", "2026-10-13",
                                  {"kids scissors", "toddler knife"}, campaign_limit=2,
                                  probe_limit=2)
    breakdowns = [params for tool, params in calls if tool == "ads_get_campaign_contribution_breakdown"]
    assert {item["campaignId"] for item in breakdowns} == {"SP1", "SP2"}
    assert all(item["limit"] >= 100 for item in breakdowns)
    assert len(breakdowns) == 4
    assert result["state"] == "verified"
    assert result["two_week_terms"] == 2
    assert len(result["observations"]) == 56


def test_one_point_per_week_is_not_a_verified_fourteen_day_curve():
    class FakeSif:
        def call(self, tool, params):
            if tool == "ads_get_asin_campaign_contribution_overview":
                return {"campaigns": [{"campaign_display_id": "SP1", "ad_type": "SP"}]}
            response = payload(params["start_date"], [8, 0, 0, 0, 0, 0, 0],
                               [5, 0, 0, 0, 0, 0, 0])
            return response

    result = collect_rank_history(FakeSif(), "US", "B012345678", "2026-10-13",
                                  {"kids scissors"}, campaign_limit=1)
    assert result["state"] == "partial"
    assert result["two_week_terms"] == 0
    assert result["natural_two_week_terms"] == 0


def test_campaign_selection_prefers_dense_rank_days_over_sparse_keyword_count():
    calls = []

    class FakeSif:
        def call(self, tool, params):
            calls.append((tool, params))
            if tool == "ads_get_asin_campaign_contribution_overview":
                return {"campaigns": [
                    {"campaign_display_id": "SP_SPARSE", "ad_type": "SP", "contribution_score": 100},
                    {"campaign_display_id": "SP_DENSE", "ad_type": "SP", "contribution_score": 10}]}
            if params["campaignId"] == "SP_DENSE":
                return payload(params["start_date"], [8]*7, [5]*7)
            first = payload(params["start_date"], [8, 0, 0, 0, 0, 0, 0],
                            [5, 0, 0, 0, 0, 0, 0])["items"][0]
            second = {**first, "keyword": "toddler knife"}
            return {"items": [first, second]}

    result = collect_rank_history(FakeSif(), "US", "B012345678", "2026-10-13",
                                  {"kids scissors", "toddler knife"}, campaign_limit=1,
                                  probe_limit=2)
    previous_calls = [params for tool, params in calls if tool == "ads_get_campaign_contribution_breakdown"
                      and params["start_date"] == "2026-09-27"]
    assert [params["campaignId"] for params in previous_calls] == ["SP_DENSE"]
    assert result["campaign_audit"][1]["selected_for_previous"] is True


def test_campaign_selection_covers_distinct_terms_instead_of_repeating_same_terms():
    calls = []

    class FakeSif:
        def call(self, tool, params):
            calls.append((tool, params))
            if tool == "ads_get_asin_campaign_contribution_overview":
                return {"campaigns": [
                    {"campaign_display_id": "SP_A", "ad_type": "SP", "contribution_score": 100},
                    {"campaign_display_id": "SP_B", "ad_type": "SP", "contribution_score": 90},
                    {"campaign_display_id": "SP_C", "ad_type": "SP", "contribution_score": 80},
                ]}
            words = {"SP_A": ["first term", "second term"],
                     "SP_B": ["first term", "second term"],
                     "SP_C": ["third term"]}[params["campaignId"]]
            return {"items": [{**payload(params["start_date"], [8]*7, [5]*7)["items"][0],
                               "keyword": word} for word in words]}

    result = collect_rank_history(FakeSif(), "US", "B012345678", "2026-10-13",
                                  {"first term", "second term", "third term"},
                                  campaign_limit=2, probe_limit=3)
    previous_calls = [params["campaignId"] for tool, params in calls
                      if tool == "ads_get_campaign_contribution_breakdown"
                      and params["start_date"] == "2026-09-27"]
    assert previous_calls == ["SP_A", "SP_C"]
    assert result["two_week_terms"] == 3


def test_campaign_selection_uses_backup_natural_source_when_first_previous_week_is_empty():
    calls = []

    class FakeSif:
        def call(self, tool, params):
            calls.append((tool, params))
            if tool == "ads_get_asin_campaign_contribution_overview":
                return {"campaigns": [
                    {"campaign_display_id": "SP_A", "ad_type": "SP", "contribution_score": 100},
                    {"campaign_display_id": "SP_B", "ad_type": "SP", "contribution_score": 90},
                    {"campaign_display_id": "SP_C", "ad_type": "SP", "contribution_score": 80},
                ]}
            if params["campaignId"] == "SP_C":
                response = payload(params["start_date"], [0]*7, [5]*7)
                response["items"][0]["keyword"] = "ad only term"
                return response
            if params["campaignId"] == "SP_A" and params["start_date"] == "2026-09-27":
                return {"items": []}
            return payload(params["start_date"], [8]*7, [5]*7)

    result = collect_rank_history(FakeSif(), "US", "B012345678", "2026-10-13",
                                  {"kids scissors", "ad only term"}, campaign_limit=2,
                                  probe_limit=3)
    previous_calls = [params["campaignId"] for tool, params in calls
                      if tool == "ads_get_campaign_contribution_breakdown"
                      and params["start_date"] == "2026-09-27"]
    assert previous_calls == ["SP_A", "SP_B"]
    assert result["natural_two_week_terms"] == 1


def test_historical_replay_gap_is_not_reported_as_live_sif_failure():
    class MissingReplay:
        def call(self, tool, params):
            raise ReplayMissing("no recorded response")

    result = collect_rank_history(MissingReplay(), "US", "B012345678", "2026-10-13",
                                  {"kids scissors"})
    assert result["state"] == "replay_missing"


def test_dated_campaign_rank_replaces_same_run_summary_position(tmp_path):
    state = StateStore(tmp_path / "state.sqlite3")
    key = state.add_keyword("US", "B012345678", "kids scissors", "sif_asin_signals", "SIF", "r1", "s1")
    state.record_rank(key, "2026-10-12", "advertising", None, "reported_position", "r1", display="p1,9/12")
    state.record_rank(key, "2026-10-12", "advertising", 9, "absolute_rank", "r1", display="p1,9/12 · g1")
    rows = state.rank_window(key, "2026-10-12", "2026-10-12")
    assert len(rows) == 1 and rows[0]["rank"] == 9 and rows[0]["state"] == "absolute_rank"


def test_current_sif_page_position_is_shown_without_false_absolute_rank():
    fields = current_rank_fields({"organic_rank": "p1,9/48", "sp_rank": "p2,3/12"})
    assert fields["natural_rank"] is None
    assert fields["natural_rank_display"] == "p1,9/48"
    assert fields["ad_rank_display"] == "p2,3/12"
    assert current_rank_fields({"organic_rank": 17})["natural_rank"] == 17


def test_single_asin_supplement_retains_both_complete_sif_weeks(tmp_path):
    from datetime import date

    class FakeSif:
        def call(self, tool, params):
            if tool == "market_get_asin_keyword_signals":
                return {"top_keywords": [{"keyword": "kids scissors", "organic_rank": "p1,8/48",
                                          "organic_rank_time_us": "2026-10-12 10:00"}]}
            if tool == "ads_get_asin_campaign_contribution_overview":
                return {"campaigns": [{"campaign_display_id": "SP1", "ad_type": "SP",
                                       "contribution_score": 5}]}
            if tool == "ads_get_campaign_contribution_breakdown":
                return payload(params["start_date"], [8]*7, [5]*7)
            if tool == "market_get_keyword_history":
                return []
            raise AssertionError(tool)

    run_dir = tmp_path / "b-20261013-000000-test"
    run_dir.mkdir()
    state = StateStore(tmp_path / "state.sqlite3")
    result = query_single_sif(FakeSif(), state, run_dir,
                              {"site": "US", "asin": "B012345678", "sid": "1"},
                              today=date(2026, 10, 13))
    row = next(term for term in result["terms"] if term["normalized"] == "kids scissors")
    assert row["rank_window"] == ["2026-09-27", "2026-10-10"]
    assert row["rank_14d_state"] == result["rank_state"]
    assert len([point for point in row["rank_observations"] if point["channel"] == "natural"]) == 14


def test_single_asin_supplement_does_not_borrow_missing_days_from_older_query(tmp_path):
    from datetime import date

    class FakeSif:
        def call(self, tool, params):
            if tool == "market_get_asin_keyword_signals":
                return {"top_keywords": [{"keyword": "kids scissors"}]}
            if tool == "ads_get_asin_campaign_contribution_overview":
                return {"campaigns": [{"campaign_display_id": "SP1", "ad_type": "SP"}]}
            if tool == "ads_get_campaign_contribution_breakdown":
                return (payload(params["start_date"], [8]*7, [5]*7)
                        if params["start_date"] == "2026-10-04" else {"items": []})
            if tool == "market_get_keyword_history":
                return []
            raise AssertionError(tool)

    run_dir = tmp_path / "b-20261013-000000-test"
    run_dir.mkdir()
    state = StateStore(tmp_path / "state.sqlite3")
    key = state.add_keyword("US", "B012345678", "kids scissors", "sif_asin_signals", "SIF", "old", "1")
    for day in range(27, 31):
        state.record_rank(key, f"2026-09-{day}", "natural", 9, "absolute_rank", "old")
    for day in range(1, 4):
        state.record_rank(key, f"2026-10-0{day}", "natural", 9, "absolute_rank", "old")
    result = query_single_sif(FakeSif(), state, run_dir,
                              {"site": "US", "asin": "B012345678", "sid": "1"},
                              today=date(2026, 10, 13))
    row = next(term for term in result["terms"] if term["normalized"] == "kids scissors")
    assert result["rank_state"] == "partial"
    assert row["rank_14d_state"] == "partial"
    assert all(point["run_id"] == result["query_id"] for point in row["rank_observations"])
    assert not any(point["observed_date"] <= "2026-10-03" for point in row["rank_observations"])
