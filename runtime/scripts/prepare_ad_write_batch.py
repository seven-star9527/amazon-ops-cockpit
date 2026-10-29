"""Build a frozen, reviewable ad write batch from panel decisions.

The panel only stores opinions. This command is the bridge the operator's
agent runs before any remote write. It never calls a write tool.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from b_ops.model.storage import StateStore


def _action_index(board: dict) -> dict[str, dict]:
    result = {}
    for action in board.get("actions") or []:
        if isinstance(action, dict) and action.get("action_key"):
            result[str(action["action_key"])] = action
    for product in (board.get("products") or {}).values():
        for action in product.get("actions") or []:
            if isinstance(action, dict) and action.get("action_key"):
                result[str(action["action_key"])] = action
    return result


def _product_index(board: dict) -> dict[str, dict]:
    result = {}
    for product in (board.get("products") or {}).values():
        meta = {"product_name": product.get("name"), "asin": product.get("asin"),
                "affected_asins": product.get("affected_asins") or [product.get("asin")]}
        for action in product.get("actions") or []:
            if action.get("action_key"):
                result[str(action["action_key"])] = meta
    return result


def _negative_match(action: dict) -> str:
    if action.get("action_type") == "phrase_negative_candidate":
        return "negativePhrase"
    if action.get("action_type") in {"negative_keyword_candidate", "keep_root_negative_bad_tail"}:
        return "negativeExact"
    matches = {str(value).lower() for value in action.get("match_types") or []}
    return "negativePhrase" if matches == {"phrase"} else "negativeExact"


def _canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _group_active(board: dict, profile_id: str, campaign_id: str, ad_group_id: str,
                  action: dict | None = None) -> bool:
    if any(str(row.get("profile_id")) == str(profile_id)
           and str(row.get("campaign_id")) == str(campaign_id)
           and str(row.get("ad_group_id")) == str(ad_group_id)
           and row.get("campaign_state") == "enabled"
           and row.get("ad_group_state") == "enabled"
           for row in (board.get("ad_group_options") or board.get("ad_keyword_targets") or [])):
        return True
    # ASIN / product-target groups often have no keyword-target rows. Use the
    # action's own source evidence when it points at this exact group.
    if action and str(action.get("campaign_id")) == str(campaign_id) and str(action.get("ad_group_id")) == str(ad_group_id):
        return any(str(row.get("profile_id")) == str(profile_id)
                   and row.get("campaign_state") == "enabled"
                   and row.get("ad_group_state") == "enabled"
                   for row in action.get("source_rows") or [])
    return False


def build(board: dict, decisions: dict[str, dict]) -> dict:
    actions = _action_index(board)
    product_index = _product_index(board)
    items, blocked = [], []
    for key, decision in decisions.items():
        action = actions.get(key)
        if not action:
            blocked.append({"action_key": key, "reason": "动作已不在当前批次"})
            continue
        value = decision.get("value")
        if value not in {"accept", "modify"}:
            continue
        if action.get("processed_status"):
            blocked.append({"action_key": key, "reason": "来源已处理"})
            continue
        if not action.get("campaign_name") or not action.get("ad_group_name") or \
                str(action.get("ad_group_name")).isdigit():
            blocked.append({"action_key": key, "reason": "广告活动或广告组名称未解析，禁止只带 ID 写回"})
            continue
        kind = action.get("kind")
        profile = str(action.get("profile_id") or "")
        decision_version = decision.get("version")
        product_meta = product_index.get(key, {})
        common = {"action_key": key, "profile_id": profile,
                  "decision_version": decision_version, "decision_value": value,
                  "product_name": product_meta.get("product_name"),
                  "asin": action.get("asin") or product_meta.get("asin"),
                  "affected_asins": action.get("affected_asins") or product_meta.get("affected_asins") or [],
                  "portfolio_id": action.get("portfolio_id"),
                  "portfolio_name": action.get("portfolio_name"),
                  "campaign_id": str(action.get("campaign_id") or ""),
                  "ad_group_id": str(action.get("ad_group_id") or ""),
                  "campaign_name": action.get("campaign_name"),
                  "ad_group_name": action.get("ad_group_name")}
        if kind in {"negative", "negative_asin"}:
            if action.get("existing_negative"):
                blocked.append({"action_key": key, "reason": "来源标记已存在否定"})
                continue
            if not common["campaign_id"] or not common["ad_group_id"]:
                blocked.append({"action_key": key, "reason": "Campaign 或广告组缺失"})
                continue
            if kind == "negative":
                items.append({**common, "write_type": "negative_keyword",
                              "tool": "advertising_add_negative_keywords",
                              "query": action.get("query"),
                              "match_type": _negative_match(action),
                              "params": {"profileId": int(profile),
                                         "negativeKeywords": [{
                                             "campaignId": common["campaign_id"],
                                             "adGroupId": common["ad_group_id"],
                                             "keyword": action.get("query"),
                                             "matchType": _negative_match(action),
                                             "state": "ENABLED"}]}})
            else:
                asin = str(action.get("query") or "").strip().upper()
                if not re.fullmatch(r"[A-Z0-9]{10}", asin):
                    blocked.append({"action_key": key, "reason": "否定 ASIN 格式无效"})
                    continue
                items.append({**common, "write_type": "negative_asin",
                              "tool": "advertising_add_negative_targets",
                              "query": asin,
                              "match_type": "negativeProductExact",
                              "params": {"profileId": int(profile),
                                         "asins": [{"campaignId": common["campaign_id"],
                                                    "adGroupId": common["ad_group_id"],
                                                    "asin": asin, "state": "ENABLED"}]}})
        elif kind == "exact":
            if action.get("existing_exact"):
                blocked.append({"action_key": key, "reason": "已有精准目标"})
                continue
            target_campaign = str(decision.get("target_campaign_id") or (action.get("exact_plan") or {}).get("target_campaign_id") or "")
            target_group = str(decision.get("target_ad_group_id") or (action.get("exact_plan") or {}).get("target_ad_group_id") or "")
            bid = decision.get("bid")
            if not target_campaign or not target_group:
                blocked.append({"action_key": key, "reason": "未选择精准承接广告组"})
                continue
            if bid is None or not (0 < float(bid) <= 1000):
                blocked.append({"action_key": key, "reason": "未确认精准出价"})
                continue
            if not _group_active(board, profile, target_campaign, target_group, action):
                blocked.append({"action_key": key, "reason": "承接广告组不在当前有效范围"})
                continue
            target_row = next((row for row in (board.get("ad_group_options") or board.get("ad_keyword_targets") or [])
                               if str(row.get("campaign_id")) == target_campaign
                               and str(row.get("ad_group_id")) == target_group), None)
            if not target_row or not target_row.get("ad_group_name") or str(target_row.get("ad_group_name")).isdigit():
                blocked.append({"action_key": key, "reason": "承接广告组名称未解析"})
                continue
            object_type = str((action.get("exact_plan") or {}).get("object_type") or "keyword")
            if object_type == "asin":
                asin = str(action.get("query") or "").strip().upper()
                if not re.fullmatch(r"[A-Z0-9]{10}", asin):
                    blocked.append({"action_key": key, "reason": "精准 ASIN 格式无效"})
                    continue
                items.append({**common, "write_type": "exact_product",
                              "tool": "post_targets_sp",
                              "query": asin,
                              "match_type": "PRODUCT_EXACT",
                              "target_campaign_id": target_campaign,
                              "target_ad_group_id": target_group,
                              "bid": float(bid),
                              "params": {"profile_id": profile, "api_version": "adsV1",
                                         "module_name": "Mcp", "one_more": 0,
                                         "api_method": "post_targets", "ad_type": "sp",
                                         "api_params": {"targets": [{
                                             "adProduct": "SPONSORED_PRODUCTS", "negative": False,
                                             "campaignId": target_campaign, "adGroupId": target_group,
                                             "targetType": "PRODUCT", "state": "enabled",
                                             "bid": str(float(bid)),
                                             "targetDetails": {"productTarget": {
                                                 "product": {"productId": asin},
                                                 "productIdType": "ASIN",
                                                 "matchType": "PRODUCT_EXACT"}}}]}}})
            else:
                items.append({**common, "write_type": "exact_keyword",
                              "tool": "advertising_sp_add_keywords",
                              "query": action.get("query"),
                              "match_type": "EXACT",
                              "target_campaign_id": target_campaign,
                              "target_ad_group_id": target_group,
                              "bid": float(bid),
                              "params": {"profileId": int(profile),
                                         "keywords": [{"campaignId": target_campaign,
                                                       "adGroupId": target_group,
                                                       "keyword": action.get("query"),
                                                       "matchType": "EXACT",
                                                       "state": "ENABLED",
                                                       "bid": float(bid)}]}})
        elif kind == "bid_review":
            target_id = str(action.get("target_id") or "")
            bid = decision.get("bid")
            if not target_id:
                blocked.append({"action_key": key, "reason": "缺少 Target ID"})
                continue
            if bid is None or not (0 < float(bid) <= 1000):
                blocked.append({"action_key": key, "reason": "未确认目标竞价"})
                continue
            if not any(str(row.get("target_id")) == target_id
                       and str(row.get("profile_id")) == profile
                       and row.get("target_state") == "enabled"
                       for row in board.get("ad_keyword_targets") or []):
                blocked.append({"action_key": key, "reason": "Target 不在当前有效范围"})
                continue
            items.append({**common, "write_type": "bid",
                          "tool": "put_targets_sp",
                          "query": action.get("query"),
                          "target_id": target_id,
                          "bid": float(bid),
                          "old_bid": (action.get("bid_evidence") or {}).get("base_bid"),
                          "params": {"profile_id": profile, "api_version": "adsV1",
                                     "module_name": "Mcp", "one_more": 0,
                                     "api_method": "put_targets", "ad_type": "sp",
                                     "api_params": {"targets": [{"targetId": target_id,
                                                                  "bid": str(float(bid))}]}}})
        else:
            blocked.append({"action_key": key, "reason": f"不支持的写入类型: {kind}"})
    # One action per exact key, stable order.
    dedup = {}
    for item in items:
        dedup[(item["write_type"], item["action_key"])] = item
    items = sorted(dedup.values(), key=lambda item: (item["write_type"], item["action_key"]))
    digest = hashlib.sha256(_canonical(items).encode("utf-8")).hexdigest()
    batch_id = f"adwrite-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{digest[:8]}"
    return {
        "schema": "amazon-ops-b/ad-write-batch/1",
        "run_id": board.get("run_id"),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "batch_id": batch_id,
        "content_sha256": digest,
        "items": items,
        "blocked": blocked,
        "summary": dict(Counter(item["write_type"] for item in items)),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--board", type=Path, required=True)
    ap.add_argument("--state", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    board = json.loads(args.board.read_text(encoding="utf-8"))
    decisions = StateStore(args.state).latest_decisions(board["run_id"])
    batch = build(board, decisions)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(batch, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"batch_id": batch["batch_id"], "digest": batch["content_sha256"],
                      "items": len(batch["items"]), "blocked": len(batch["blocked"]),
                      "summary": batch["summary"], "out": str(args.out)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
