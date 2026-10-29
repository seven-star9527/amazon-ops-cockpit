"""Validate B-line board coverage, source ledger hashes and safe action identities."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from b_ops.collect.sif_ranks import recent_rank_windows


def validate_ad_actions(actions: list[dict]) -> None:
    assert len({a["action_key"] for a in actions}) == len(actions)
    assert all(a["profile_id"] and a["query"] for a in actions)
    for action in actions:
        if action.get("reviewable"):
            assert action.get("campaign_id") and action.get("ad_group_id") and action.get("affected_asins")
            assert not action.get("processed_status") and not action.get("blocked_reason")
            if action["kind"] == "bid_review":
                assert action.get("target_id") and action.get("bid_evidence", {}).get("target_id") == action["target_id"]
                children = (action.get("rank_evidence") or {}).get("children") or {}
                rank = action.get("rank_evidence") or {}
                reference = rank.get("reference_asin")
                assert reference in action["affected_asins"]
                item = children.get(reference) or {}
                def days(channel):
                    weeks = item.get(f"{channel}_week_days")
                    if isinstance(weeks, list) and len(weeks) == 2:
                        return sum(max(0, int(day or 0)) for day in weeks)
                    if item.get(f"{channel}_days") is not None:
                        return max(0, int(item[f"{channel}_days"]))
                    return int(item.get("observed_days") or 0) if item.get("state") == "verified" else 0
                assert ((item.get("natural_latest") is not None and days("natural") >= 3) or
                        ((item.get("advertising_latest") is not None or
                          item.get("advertising_page_latest") is not None) and days("advertising") >= 3))
                assert action.get("direction") in {"consider_raise", "consider_lower"}
                assert (action.get("bid_evidence") or {}).get("budget", 0) > 0
                assert (action.get("bid_evidence") or {}).get("base_bid", 0) > 0
            else:
                assert action.get("source_count", 0) > 0
        if action.get("executable"):
            assert action["kind"] in {"negative", "negative_asin"}
            assert action["affected_asins"] and action["sponsored_type"] == "sp"
        if action["kind"] == "exact" and action.get("reviewable"):
            plan = action.get("exact_plan") or {}
            valid_single = plan.get("promoted_asin") in action["affected_asins"]
            valid_shared = (action.get("parent_scope") == "verified_same_parent" and
                            len(action["affected_asins"]) > 1 and plan.get("target_required"))
            assert (valid_single or valid_shared) and (action.get("suggested_bid") or 0) > 0
        if action["kind"] == "bid_review":
            assert not action.get("executable") and action.get("target_id")


def validate_transport_provenance(status: dict, calls: list[dict]) -> None:
    transport = status.get("sif_transport") or {}
    if transport.get("state") not in {"same_day_b_raw_resume_live", "same_day_b_complete_extend_live"}:
        return
    sif_calls = [call for call in calls if call.get("provider") == "sif"]
    source_run = transport["source_run_id"]
    reused = [call for call in sif_calls if call.get("replayed_from_b_run") == source_run]
    assert len(reused) == transport["reused_calls"]
    assert len(sif_calls) - len(reused) == transport["live_calls"]
    assert all(call.get("replayed_from_b_run") in {None, source_run} for call in sif_calls)


def audit(run_id: str) -> dict:
    if not re.fullmatch(r"b-[0-9]{8}-[0-9]{6}-[a-z0-9]+",run_id):
        raise ValueError("invalid B run ID")
    run=ROOT/"storage"/"runs"/run_id
    board_bytes=(run/"board.json").read_bytes()
    board=json.loads(board_bytes)
    manifest=json.loads((run/"manifest.json").read_text(encoding="utf-8"))
    assert manifest["state"]=="complete" and board["run_id"]==manifest["run_id"]==run_id
    assert hashlib.sha256(board_bytes).hexdigest()==manifest["batch_sha256"]
    validate_transport_provenance(board["status"], manifest["source_calls"])
    source_counts=Counter()
    source_files=set()
    for source in manifest["source_calls"]:
        target=(run/source["file"]).resolve()
        assert target.is_relative_to(run.resolve()) and target.is_file()
        assert hashlib.sha256(target.read_bytes()).hexdigest()==source["sha256"]
        source_files.add(source["file"])
        source_counts[f"{source['provider']}:{source['tool']}"]+=1
    products=board["products"]
    assert len(products)==board["coverage"]["products"]
    assert len({(p["sid"],p["site"],p["asin"]) for p in products.values()})==len(products)
    assert all(len(p["weeks"])==8 and p["name"] and p["stock"].get("source") in {"get_fba_stock_list","listing_only_unverified"} for p in products.values())
    assert sum(p["status"]=="1" for p in products.values())==board["coverage"]["active"]
    actions=board["actions"]
    validate_ad_actions(actions)
    terms=board["keyword_snapshot"]
    assert set(terms)==set(products)
    rank_obs=[obs for value in terms.values() for term in value["terms"] for obs in term["rank_observations"]]
    assert all(obs["rank"] is None or obs["rank"]>0 for obs in rank_obs)
    sif_queried=sum(value["sif_state"] in {"verified","no_rows","source_failed","replay_missing"} for value in terms.values())
    assert sif_queried==board["status"]["sif"]["queried_products"]
    assert all(value.get("rank_terms_two_week",0)>0 and value.get("rank_windows_completed",0)>=2
               for value in terms.values() if value.get("rank_history_state")=="verified")
    report={"run_id":run_id,"board_sha256":manifest["batch_sha256"],"source_calls":len(manifest["source_calls"]),
            "unique_source_files":len(source_files),"shops":board["status"]["catalog"]["shops"],
            "products":len(products),"active":board["coverage"]["active"],"problem":board["coverage"]["problem"],
            "missing_product_weeks":board["coverage"]["performance_missing_weeks"],
            "products_without_fba_row":sum(p["stock"]["source"]!="get_fba_stock_list" for p in products.values()),
            "search_term_rows":sum(item["rows"] for key,item in board["status"].items() if key.startswith("search_terms:")),
            "actions":len(actions),"reviewable_actions":sum(bool(a.get("reviewable")) for a in actions),
            "executable_actions":sum(a["executable"] for a in actions),
            "processed_actions":sum(bool(a.get("processed_status")) for a in actions),
            "exact_plans":sum(a["kind"]=="exact" for a in actions),
            "bid_reviews":sum(a["kind"]=="bid_review" for a in actions),
            "keyword_target_rows":len(board.get("ad_keyword_targets") or []),
            "competitor_queries":source_counts.get("sif:market_discover_competitors",0),
            "shared_actions":sum(a["shared_group"] for a in actions),
            "sif_products_queried":sif_queried,
            "sif_products_successful":board["status"]["sif"].get("successful_products"),
            "sif_products_deferred":board["status"]["sif"].get("deferred_products"),
            "sif_replay_missing_products":board["status"]["sif"].get("replay_missing_products",0),
            "sif_products_with_two_week_ranks":sum(value.get("rank_terms_two_week",0)>0 for value in terms.values()),
            "sif_two_week_rank_terms":sum(value.get("rank_terms_two_week",0) for value in terms.values()),
            "tracked_terms":sum(len(value["terms"]) for value in terms.values()),
            "daily_absolute_rank_observations":sum(obs["state"]=="absolute_rank" for obs in rank_obs),
            "daily_reported_natural_position_observations":sum(obs["state"]=="reported_position" and obs["channel"]=="natural" for obs in rank_obs),
            "daily_reported_ad_position_observations":sum(obs["state"]=="reported_position" and obs["channel"]=="advertising" for obs in rank_obs),
            "source_tools":dict(source_counts)}
    return report


def audit_supplement(run_dir: Path, query_id: str) -> dict:
    """Audit a live SIF supplement separately from its immutable B batch."""
    assert re.fullmatch(r"sif-[0-9]{8}-[0-9]{6}-[a-z0-9]+", query_id)
    run = Path(run_dir).resolve()
    folder = (run / "supplements" / query_id).resolve()
    assert folder.is_relative_to(run) and folder.is_dir()
    board = json.loads((run / "board.json").read_text(encoding="utf-8"))
    summary = json.loads((folder / "summary.json").read_text(encoding="utf-8"))
    assert board["run_id"] == summary["run_id"] == run.name
    assert summary["query_id"] == query_id
    matches = [product for product in board["products"].values()
               if str(product["sid"]) == str(summary["sid"]) and
               product["asin"] == summary["asin"] and
               (not summary.get("site") or product["site"] == summary["site"])]
    assert len(matches) == 1
    windows = recent_rank_windows(summary["as_of_date"])
    start, end = windows[0][0], windows[-1][1]
    assert summary["rank_window"] == [start, end]
    assert summary["source_calls"]
    for call in summary["source_calls"]:
        assert call["provider"] == "sif"
        source = (folder / call["file"]).resolve()
        assert source.is_relative_to(folder) and source.is_file()
        assert hashlib.sha256(source.read_bytes()).hexdigest() == call["sha256"]
    two_week, natural_two_week, ad_two_week = set(), set(), set()
    natural_full = set()
    observed_count = 0
    for term in summary["terms"]:
        per_channel = {"natural": [set(), set()], "advertising": [set(), set()]}
        seen = set()
        for point in term["rank_observations"]:
            observed_count += 1
            assert point["run_id"] == query_id
            assert start <= point["observed_date"] <= end
            assert point["channel"] in per_channel
            identity = point["observed_date"], point["channel"]
            assert identity not in seen
            seen.add(identity)
            rank = point["rank"]
            assert rank is None or rank > 0
            if point["state"] == "absolute_rank":
                assert rank is not None
                index = 0 if point["observed_date"] <= windows[0][1] else 1
                per_channel[point["channel"]][index].add(point["observed_date"])
        word = term["keyword"].casefold().strip()
        if any(len(weeks[0]) >= 5 and len(weeks[1]) >= 5 for weeks in per_channel.values()):
            two_week.add(word)
        if all(len(week) >= 5 for week in per_channel["natural"]):
            natural_two_week.add(word)
        if all(len(week) >= 5 for week in per_channel["advertising"]):
            ad_two_week.add(word)
        if sum(map(len, per_channel["natural"])) == 14:
            natural_full.add(word)
    assert len(two_week) == summary["rank_terms_two_week"]
    assert len(natural_two_week) == summary["rank_natural_terms_two_week"]
    assert len(ad_two_week) == summary["rank_ad_terms_two_week"]
    if summary["rank_state"] == "verified":
        assert two_week and summary["rank_windows_completed"] >= 2
    return {"query_id": query_id, "run_id": run.name, "asin": summary["asin"],
            "source_calls": len(summary["source_calls"]), "terms": len(summary["terms"]),
            "two_week_terms": len(two_week), "natural_two_week_terms": len(natural_two_week),
            "ad_two_week_terms": len(ad_two_week), "natural_14_day_terms": len(natural_full),
            "rank_observations": observed_count}


def main():
    parser=argparse.ArgumentParser();parser.add_argument("run_id")
    parser.add_argument("--supplement", help="audit a SIF single-ASIN query ID")
    args=parser.parse_args()
    result=(audit_supplement(ROOT/"storage"/"runs"/args.run_id,args.supplement)
            if args.supplement else audit(args.run_id))
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=="__main__":main()
