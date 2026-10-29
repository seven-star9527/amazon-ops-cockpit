from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from prepare_ad_write_batch import build
import execute_ad_write_batch as executor
from execute_ad_write_batch import preflight, split_items


def _board():
    groups = [
        {"profile_id": "123", "campaign_id": "c1", "campaign_name": "C1", "ad_group_id": "g1",
         "ad_group_name": "G1", "campaign_state": "enabled", "ad_group_state": "enabled",
         "target_id": "t1", "target_state": "enabled"},
        {"profile_id": "123", "campaign_id": "c2", "campaign_name": "C2", "ad_group_id": "g2",
         "ad_group_name": "G2", "campaign_state": "enabled", "ad_group_state": "enabled",
         "target_id": "t2", "target_state": "enabled"},
    ]
    negative = {"action_key": "neg", "kind": "negative", "profile_id": "123",
                "campaign_id": "c1", "campaign_name": "Campaign 1", "ad_group_id": "g1", "ad_group_name": "Group 1", "query": "bad term",
                "action_type": "negative_keyword_candidate", "existing_negative": False,
                "processed_status": "", "reviewable": True}
    exact = {"action_key": "exact", "kind": "exact", "profile_id": "123",
             "campaign_id": "c1", "campaign_name": "Campaign 1", "ad_group_id": "g1", "ad_group_name": "Group 1", "query": "good term",
             "existing_exact": False, "processed_status": "", "reviewable": False,
             "exact_plan": {"target_campaign_id": "", "target_ad_group_id": ""}}
    bid = {"action_key": "bid", "kind": "bid_review", "profile_id": "123",
           "campaign_id": "c1", "campaign_name": "Campaign 1", "ad_group_id": "g1", "ad_group_name": "Group 1", "target_id": "t1",
           "query": "good term", "processed_status": "", "reviewable": True}
    return {"run_id": "b-test", "actions": [negative, exact, bid],
            "ad_keyword_targets": groups, "products": {}}


def test_batch_builds_negative_exact_and_bid_with_confirmed_destinations():
    decisions = {
        "neg": {"version": 4, "value": "accept"},
        "exact": {"version": 4, "value": "accept", "bid": 0.7,
                  "target_campaign_id": "c2", "target_ad_group_id": "g2"},
        "bid": {"version": 4, "value": "accept", "bid": 0.55},
    }
    batch = build(_board(), decisions)
    assert batch["summary"] == {"bid": 1, "exact_keyword": 1, "negative_keyword": 1}
    assert not batch["blocked"]
    by_type = {item["write_type"]: item for item in batch["items"]}
    assert by_type["negative_keyword"]["tool"] == "advertising_add_negative_keywords"
    assert by_type["negative_keyword"]["match_type"] == "negativeExact"
    assert by_type["exact_keyword"]["tool"] == "advertising_sp_add_keywords"
    assert by_type["exact_keyword"]["target_ad_group_id"] == "g2"
    assert by_type["exact_keyword"]["params"]["keywords"][0]["bid"] == 0.7
    assert by_type["bid"]["tool"] == "put_targets_sp"
    assert by_type["bid"]["params"]["api_params"]["targets"][0] == {"targetId": "t1", "bid": "0.55"}
    assert preflight(batch, _board()) == []


def test_exact_without_destination_is_blocked():
    decisions = {"exact": {"version": 4, "value": "accept", "bid": 0.7}}
    batch = build(_board(), decisions)
    assert not batch["items"]
    assert batch["blocked"][0]["reason"] == "未选择精准承接广告组"


def test_product_exact_uses_post_targets_not_keyword_tool():
    board = _board()
    board["actions"][1]["exact_plan"]["object_type"] = "asin"
    board["actions"][1]["query"] = "B0FGTVP62B"
    decisions = {"exact": {"version": 4, "value": "accept", "bid": 0.7,
                           "target_campaign_id": "c1", "target_ad_group_id": "g1"}}
    batch = build(board, decisions)
    item = next(item for item in batch["items"] if item["action_key"] == "exact")
    assert item["write_type"] == "exact_product"
    assert item["tool"] == "post_targets_sp"
    assert item["params"]["api_params"]["targets"][0]["targetDetails"]["productTarget"]["product"]["productId"] == "B0FGTVP62B"
    assert preflight(batch, board) == []


def test_one_bad_item_does_not_block_the_rest():
    decisions = {
        "neg": {"version": 4, "value": "accept"},
        "exact": {"version": 4, "value": "accept", "bid": 0.7,
                  "target_campaign_id": "c2", "target_ad_group_id": "g2"},
    }
    batch = build(_board(), decisions)
    batch["items"][0]["profile_id"] = ""
    valid, blocked = split_items(batch)
    assert blocked
    assert valid
    assert any(item.get("write_type") == "negative_keyword" for item in valid)


def test_execute_continues_after_one_unknown_item(monkeypatch):
    batch = {
        "schema": "amazon-ops-b/ad-write-batch/1",
        "batch_id": "b1", "content_sha256": "x", "created_at": "2026-10-24T00:00:00+00:00",
        "items": [
            {"action_key": "a", "write_type": "negative_keyword", "profile_id": "1",
             "campaign_id": "c", "ad_group_id": "g", "tool": "advertising_add_negative_keywords", "params": {}},
            {"action_key": "b", "write_type": "negative_keyword", "profile_id": "1",
             "campaign_id": "c", "ad_group_id": "g", "tool": "advertising_add_negative_keywords", "params": {}},
        ],
    }
    calls = []
    class FakeClient:
        def __init__(self, *args, **kwargs): pass
        def write(self, tool, params):
            calls.append(params)
            if len(calls) == 1:
                raise RuntimeError("transport uncertainty")
            return {"code": 1}
    monkeypatch.setenv("LINGXING_MCP_KEY", "test")
    monkeypatch.setattr(executor, "LingxingClient", FakeClient)
    receipt = executor.execute(batch, "b1:x", dry_run=False)
    assert [row["status"] for row in receipt["results"]] == ["unknown", "succeeded"]
    assert len(calls) == 2
