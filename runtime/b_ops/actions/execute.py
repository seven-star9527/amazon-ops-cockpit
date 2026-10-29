"""Single-item Lingxing advertising writer with frozen confirmation and no blind retry."""

from __future__ import annotations

from datetime import datetime, timezone

from b_ops.actions.batch import canonical_hash
from b_ops.collect.transport import JsonRpcHttp, content_object, unpack_rpc


class WriteOutcomeUnknown(RuntimeError):
    """The request might have arrived remotely. Never resend automatically."""


SCHEMA = {
    "advertising_add_negative_keywords": "negativeKeywords",
    "advertising_add_negative_targets": "asins",
}


class LingxingWriteAdapter:
    def __init__(self, url: str, key: str):
        self.transport = JsonRpcHttp(url, key, provider="lingxing", timeout=120)

    def call(self, tool: str, params: dict) -> dict:
        if tool not in SCHEMA:
            raise ValueError("unapproved write tool")
        try:
            return content_object(unpack_rpc(self.transport.post("tools/call", {
                "name": "action", "arguments": {"toolId": tool, "params": params}})))
        except Exception as exc:
            raise WriteOutcomeUnknown(type(exc).__name__) from None


def _item_result(business: dict) -> tuple[str, str, str]:
    if not isinstance(business, dict):
        return "unknown", "", "unparseable business response"
    if business.get("code") != 1 or business.get("success") is False:
        return "failed", "", str(business.get("message") or business.get("msg") or "business rejected")[:180]
    data = business.get("data")
    for _ in range(4):
        if not isinstance(data, dict):
            break
        successes, errors = data.get("success"), data.get("error")
        if isinstance(successes, list) or isinstance(errors, list):
            successes = successes if isinstance(successes, list) else []
            errors = errors if isinstance(errors, list) else []
            if errors:
                return "failed", "", str(errors[0].get("message") or errors[0])[:180]
            if len(successes) == 1 and successes[0].get("index") == 0:
                target = successes[0].get("target") or {}
                return "accepted", str(target.get("targetId") or ""), ""
            return "unknown", "", "missing item-level success"
        data = data.get("data")
    return "unknown", "", "missing item-level result"


def _params(item: dict) -> dict:
    tool = item["tool"]
    if tool not in SCHEMA:
        raise ValueError("unapproved write tool")
    payload = item["payload"]
    expected = {"campaignId", "adGroupId", "state"}
    if not expected.issubset(payload) or not payload.get("profileId"):
        raise ValueError("remote scope incomplete")
    row = {key: value for key, value in payload.items() if key != "profileId"}
    return {"profileId": payload["profileId"], SCHEMA[tool]: [row]}


def execute_batch(batch: dict, confirmation: str, writer, *, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("now needs timezone")
    exact = f"{batch.get('batch_id')}:{batch.get('content_sha256')}"
    if confirmation != exact:
        raise ValueError("exact batch confirmation required")
    core = {key: value for key, value in batch.items() if key not in {"batch_id", "content_sha256"}}
    if canonical_hash(core) != batch.get("content_sha256") or batch.get("batch_id") != f"{batch.get('run_id')}-{batch.get('content_sha256', '')[:12]}":
        raise ValueError("frozen batch hash mismatch")
    expiry = datetime.fromisoformat(batch["expires_at"].replace("Z", "+00:00"))
    if now >= expiry:
        raise ValueError("stale frozen batch")
    items = batch.get("items") or []
    if not items or len({item.get("action_key") for item in items}) != len(items):
        raise ValueError("missing or repeated frozen actions")
    params = [_params(item) for item in items]
    receipt = {"batch_id": batch["batch_id"], "content_sha256": batch["content_sha256"],
               "submitted_at": now.isoformat(), "items": []}
    unknown = False
    for item, payload in zip(items, params):
        if unknown:
            status, target_id, error = "not_submitted", "", "previous outcome unknown"
        else:
            try:
                status, target_id, error = _item_result(writer.call(item["tool"], payload))
            except WriteOutcomeUnknown as exc:
                status, target_id, error = "unknown", "", str(exc)[:180]
            except Exception as exc:
                status, target_id, error = "unknown", "", type(exc).__name__
            if status == "unknown":
                unknown = True
        receipt["items"].append({"action_key": item["action_key"], "status": status,
                                 "target_id": target_id, "error": error,
                                 "readback_status": "pending" if status == "accepted" else "not_verified"})
    return receipt
