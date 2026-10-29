import hashlib
import json

import pytest

from scripts.audit_run import audit_supplement


def make_supplement(tmp_path):
    run = tmp_path / "b-20261013-000000-test"
    run.mkdir()
    (run / "board.json").write_text(json.dumps({"run_id": run.name, "products": {
        "1|UK|B012345678": {"sid": "1", "site": "UK", "asin": "B012345678"}}}), encoding="utf-8")
    query_id = "sif-20261013-000000-test"
    folder = run / "supplements" / query_id
    (folder / "raw" / "sif").mkdir(parents=True)
    raw = folder / "raw" / "sif" / "source.json"
    raw.write_text('{"response":{"items":[]}}', encoding="utf-8")
    points = [{"observed_date": f"2026-09-{day}", "channel": "natural", "rank": 8,
               "state": "absolute_rank", "run_id": query_id} for day in range(27, 31)]
    points += [{"observed_date": f"2026-10-{day:02d}", "channel": "natural", "rank": 8,
                "state": "absolute_rank", "run_id": query_id} for day in range(1, 11)]
    summary = {"run_id": run.name, "query_id": query_id, "as_of_date": "2026-10-13",
               "sid": "1", "site": "UK", "asin": "B012345678",
               "rank_state": "verified", "rank_window": ["2026-09-27", "2026-10-10"],
               "rank_terms_two_week": 1, "rank_natural_terms_two_week": 1,
               "rank_ad_terms_two_week": 0, "rank_windows_completed": 2,
               "terms": [{"keyword": "kids scissors", "tracking": {"state": "active"},
                          "rank_observations": points}],
               "source_calls": [{"provider": "sif", "tool": "ads_get_campaign_contribution_breakdown",
                                 "file": "raw/sif/source.json",
                                 "sha256": hashlib.sha256(raw.read_bytes()).hexdigest()}]}
    target = folder / "summary.json"
    target.write_text(json.dumps(summary), encoding="utf-8")
    return run, query_id, summary, target, raw


def test_sif_supplement_audit_checks_two_week_coverage_and_source_hash(tmp_path):
    run, query_id, _, _, _ = make_supplement(tmp_path)
    report = audit_supplement(run, query_id)
    assert report["two_week_terms"] == 1
    assert report["natural_14_day_terms"] == 1
    assert report["source_calls"] == 1


def test_sif_supplement_audit_accepts_unique_legacy_product_without_site_field(tmp_path):
    run, query_id, summary, target, _ = make_supplement(tmp_path)
    summary.pop("site")
    target.write_text(json.dumps(summary), encoding="utf-8")
    assert audit_supplement(run, query_id)["two_week_terms"] == 1


def test_sif_supplement_audit_rejects_mixed_query_or_tampered_source(tmp_path):
    run, query_id, summary, target, raw = make_supplement(tmp_path)
    summary["terms"][0]["rank_observations"][0]["run_id"] = "older-query"
    target.write_text(json.dumps(summary), encoding="utf-8")
    with pytest.raises(AssertionError):
        audit_supplement(run, query_id)
    summary["terms"][0]["rank_observations"][0]["run_id"] = query_id
    target.write_text(json.dumps(summary), encoding="utf-8")
    raw.write_text("tampered", encoding="utf-8")
    with pytest.raises(AssertionError):
        audit_supplement(run, query_id)
