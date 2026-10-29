from b_ops.diagnose.inventory import inventory_issues
from b_ops.diagnose.listing import listing_issues
from b_ops.diagnose.prioritize import prioritize


def product():
    weeks = []
    for index in range(4):
        weeks.append({"label": f"W{40+index}", "units": 14, "sessions_total": 100,
                      "orders": 5, "return_count": 0, "quality": "measured", "source_ref": f"p{index}"})
    return {"key": "2|US|B012345678", "sid": "2", "site": "US", "asin": "B012345678",
            "status": "1", "stock": {"sellable": 8, "inbound_shipped": 20}, "skus": {},
            "weeks": weeks, "rating": 4.4, "reviews": 30}


def test_inventory_low_cover_is_issue_but_eta_is_gap_not_fact():
    issues = inventory_issues(product())
    assert issues[0]["type"] == "low_cover"
    assert issues[0]["evidence"]["days_cover"] == 4
    assert "ETA" in issues[0]["gaps"]
    assert issues[0]["suggested_quantity"] is None


def test_listing_conversion_fall_has_traffic_counterevidence():
    p = product()
    p["weeks"][-1]["orders"] = 1
    issues = listing_issues(p)
    issue = next(item for item in issues if item["type"] == "conversion_drop")
    assert issue["evidence"]["traffic_change"] == 0
    assert issue["hypothesis"] != "图片问题"


def test_priority_puts_stockout_before_ad_opportunity():
    issues = [{"domain": "advertising", "severity": "medium", "actionability": 1},
              {"domain": "inventory", "severity": "critical", "actionability": 1}]
    assert prioritize(issues)[0]["domain"] == "inventory"


def test_aged_and_estimated_excess_stock_create_separate_actionable_warning():
    p = product()
    p['stock'] = {'sellable':400,'age_181_plus':80,'excess_estimate':45,'storage_cost_next_month':12}
    issues = inventory_issues(p)
    assert any(item['type']=='aged_excess' for item in issues)
    assert any(item['type']=='excess_cover' for item in issues)
