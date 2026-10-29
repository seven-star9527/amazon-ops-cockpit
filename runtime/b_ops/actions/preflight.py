"""Require a targeted recent read before any advertising mutation."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone


def validate_preflight(batch: dict, check: dict, *, now: datetime | None = None):
    now = now or datetime.now(timezone.utc)
    if check.get("batch_id") != batch.get("batch_id") or check.get("content_sha256") != batch.get("content_sha256"):
        raise ValueError("preflight batch hash mismatch")
    checked = datetime.fromisoformat(str(check.get("checked_at") or "").replace("Z", "+00:00"))
    if checked.tzinfo is None or checked > now or now-checked > timedelta(minutes=10):
        raise ValueError("stale remote preflight")
    items = check.get("items") or []
    expected = {item["action_key"] for item in batch.get("items", [])}
    if len(items) != len(expected) or {item.get("action_key") for item in items} != expected:
        raise ValueError("preflight action scope incomplete")
    for item in items:
        if not item.get("group_active"):
            raise ValueError("ad group inactive")
        if not item.get("target_absent"):
            raise ValueError("duplicate remote target")
        if not item.get("source_tool") or not re.fullmatch(r"[0-9a-f]{64}", str(item.get("source_sha256") or "")):
            raise ValueError("missing remote read evidence")
