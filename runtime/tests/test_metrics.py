from b_ops.model.metrics import Metric, aligned_natural_sessions, aggregate_ratio, iso_weeks


def test_sessions_is_total_clicks_and_natural_is_guarded():
    total = Metric("sessions_total", "asin", "2026-09-28", "2026-10-04", "count", 100, "measured", "p1")
    ads = Metric("ad_clicks", "asin", "2026-09-28", "2026-10-04", "count", 25, "measured", "a1")
    result = aligned_natural_sessions(total, ads)
    assert total.label == "总点击"
    assert result.value == 75 and result.quality == "derived"
    mismatched = Metric("ad_clicks", "asin", "2026-09-27", "2026-10-03", "count", 25, "measured", "a2")
    assert aligned_natural_sessions(total, mismatched).quality == "missing"
    overflow = Metric("ad_clicks", "asin", "2026-09-28", "2026-10-04", "count", 125, "measured", "a3")
    assert aligned_natural_sessions(total, overflow).quality == "conflicting"


def test_ratio_uses_totals_not_average_of_weekly_percentages():
    assert aggregate_ratio([(10, 100), (9, 10)]) == 19 / 110
    assert aggregate_ratio([(0, 0)]) is None


def test_iso_week_labels_cover_completed_weeks_only():
    weeks = iso_weeks("2026-10-12", count=2)
    assert [(w["label"], w["start"], w["end"]) for w in weeks] == [
        ("W40", "2026-09-28", "2026-10-04"),
        ("W41", "2026-10-05", "2026-10-11"),
    ]
