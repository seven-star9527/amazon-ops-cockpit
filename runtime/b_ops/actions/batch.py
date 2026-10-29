"""Freeze one reviewed, ad-group-scoped execution proposal."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone


def canonical_hash(value: dict) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include timezone")
    return parsed.astimezone(timezone.utc)


def build_batch(board: dict, decisions: dict[str, dict], review: dict, profile_id: str,
                *, manifest: dict | None = None, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("now needs timezone")
    source_hash = (manifest or board).get("batch_sha256")
    if not source_hash or review.get("batch_sha256") != source_hash:
        raise ValueError("source hash mismatch")
    if review.get("run_id") != board.get("run_id"):
        raise ValueError("run mismatch")
    captured = _utc(board["fetched_at"])
    if captured > now or now - captured >= timedelta(hours=24):
        raise ValueError("stale source batch")
    version = max((int(row.get("version", 0)) for row in decisions.values()), default=0)
    if review.get("decision_version") != version:
        raise ValueError("decision version changed since agent review")
    approved = review.get("approved_action_keys")
    if not isinstance(approved, list) or not approved or len(approved) != len(set(approved)):
        raise ValueError("approved action list must be unique and nonempty")
    if any(key not in decisions or decisions[key].get("value") != "accept" for key in approved):
        raise ValueError("approved action lacks operator acceptance")
    action_index = {action["action_key"]: action for action in board.get("actions", [])}
    if len(action_index) != len(board.get("actions", [])):
        raise ValueError("duplicate action keys")
    items = []
    for key in sorted(approved):
        action = action_index.get(key)
        if not action or not action.get("executable"):
            raise ValueError("approved action not executable")
        decision = decisions[key]
        if str(action.get("profile_id")) != str(profile_id) or str(decision.get("profile_id")) != str(profile_id):
            raise ValueError("cross-profile action")
        if action.get("existing_negative") or (action.get("kind") == "exact" and action.get("existing_exact")):
            raise ValueError("target already exists")
        if not all(action.get(field) for field in ("campaign_id", "ad_group_id", "query")):
            raise ValueError("missing remote target scope")
        if action.get("sponsored_type") != "sp":
            raise ValueError("only SP ad-group writes are verified")
        common = {"profileId": int(profile_id), "campaignId": str(action["campaign_id"]),
                  "adGroupId": str(action["ad_group_id"])}
        kind = action.get("kind")
        if kind == "negative":
            tool = "advertising_add_negative_keywords"
            payload = {**common, "keyword": action["query"], "matchType": "negativeExact", "state": "ENABLED"}
        elif kind == "negative_asin":
            tool = "advertising_add_negative_targets"
            payload = {**common, "asin": action["query"].upper(), "state": "ENABLED"}
        else:
            raise ValueError("unsupported action kind; Exact is review-only")
        items.append({"action_key": key, "tool": tool, "payload": payload,
                      "affected_asins": action.get("affected_asins", []),
                      "source_evidence": {"clicks": action.get("clicks"), "spend": action.get("spend"),
                                          "orders": action.get("orders"), "sales": action.get("sales")}})
    frozen = {"schema": "amazon-ops-b/frozen-action-batch/1", "run_id": board["run_id"],
              "source_sha256": source_hash, "profile_id": str(profile_id),
              "decision_version": version, "reviewed_at": review.get("reviewed_at"),
              "expires_at": (captured + timedelta(hours=24)).isoformat(), "items": items}
    frozen["content_sha256"] = canonical_hash(frozen)
    frozen["batch_id"] = f"{board['run_id']}-{frozen['content_sha256'][:12]}"
    return frozen
