from b_ops.model.sales_pace import sales_pace
from b_ops.collect.sif_queue import build_sif_queue, keyword_batches
from b_ops.collect import sif_queue
from b_ops.collect.replay import ReplayMissing
from b_ops.diagnose.inventory import inventory_issues


def product(key, units, *, status="1", site="US", asin="B012345678"):
    weeks = [{"label": f"W{i:02d}", "quality": "measured" if value is not None else "missing",
              "units": value} for i, value in enumerate(units, 1)]
    return {"key": key, "sid": key.split("|")[0], "site": site, "asin": asin,
            "status": status, "weeks": weeks}


def test_sales_pace_is_one_actual_four_week_measure_with_quality():
    pace = sales_pace(product("1|US|A", [14, 14, 14, 14]))
    assert pace["units_28d"] == 56
    assert pace["actual_daily_units_28d"] == 2
    assert pace["latest_week_units"] == 14
    assert pace["quality"] == "measured"
    missing = sales_pace(product("1|US|B", [None, None, 8, 14]))
    assert missing["units_28d"] is None
    assert missing["actual_daily_units_28d"] is None
    assert missing["latest_week_units"] == 14
    assert missing["quality"] == "partial"


def test_sif_queue_uses_stable_and_recent_growth_without_calendar_month():
    stable = product("1|US|A", [14, 14, 14, 14], asin="B000000001")
    growth = product("1|US|B", [0, 0, 0, 14], asin="B000000002")
    low = product("1|US|C", [1, 1, 1, 1], asin="B000000003")
    for p in (stable, growth, low):
        p["sales_pace"] = sales_pace(p)
    result = build_sif_queue([stable, growth, low], limit=2)
    assert [(entry["asin"], entry["lane"]) for entry in result["selected"]] == [
        ("B000000001", "stable"), ("B000000002", "recent_growth")]
    assert result["deferred"][low["key"]] == "below_sales_threshold"


def test_manual_priority_and_same_site_asin_reuse_one_sif_call():
    a = product("1|US|A", [0, 0, 0, 0], asin="B000000001")
    b = product("2|US|A", [0, 0, 0, 0], asin="B000000001")
    for p in (a, b):
        p["sales_pace"] = sales_pace(p)
    result = build_sif_queue([a, b], manual_priority={a["key"]}, limit=1)
    assert len(result["selected"]) == 1
    assert result["selected"][0]["lane"] == "operator_priority"
    assert {p["key"] for p in result["selected"][0]["products"]} == {a["key"], b["key"]}


def test_inventory_uses_canonical_sales_pace_instead_of_recomputing():
    p = product("1|US|A", [14, 14, 14, 14])
    p["stock"] = {"sellable": 20}
    p["sales_pace"] = {"actual_daily_units_28d": 1.0, "quality": "measured",
                       "source_weeks": ["W01", "W02", "W03", "W04"]}
    issues = inventory_issues(p)
    assert not any(issue["type"] == "low_cover" for issue in issues)


def test_core_keyword_volume_requests_are_chunked_without_first_ten_cap():
    terms = [f"term {i}" for i in range(23)]
    batches = keyword_batches(terms, size=10)
    assert [len(batch) for batch in batches] == [10, 10, 3]
    assert [word for batch in batches for word in batch] == terms


def test_rank_budget_counts_successful_signal_products_not_queue_positions():
    assert hasattr(sif_queue, "SifRunBudget")
    budget = sif_queue.SifRunBudget(rank_limit=2)
    assert budget.record_signal_error(ReplayMissing("not recorded")) == "replay_missing"
    assert budget.can_query_signal()
    assert budget.record_signal_error(RuntimeError("live failure")) == "source_failed"
    assert budget.can_query_signal()
    budget.record_signal_success()
    assert budget.reserve_rank()
    budget.record_signal_success()
    assert budget.reserve_rank()
    budget.record_signal_success()
    assert not budget.reserve_rank()


def test_default_rank_budget_can_cover_the_full_25_asin_signal_queue():
    budget = sif_queue.SifRunBudget()
    assert all(budget.reserve_rank() for _ in range(25))
    assert not budget.reserve_rank()
