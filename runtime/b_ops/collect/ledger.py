"""Persist source responses without ever persisting credentials."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

_SECRET_KEY = re.compile(r"(?:authorization|api[_-]?key|mcp[_-]?key|secret|token|password)", re.I)
_QUERY_SECRET = re.compile(r"([?&](?:secret-key|api[_-]?key|token|key)=)[^&#\s]+", re.I)


def redact(value):
    """Remove credential-bearing fields and query values recursively."""
    if isinstance(value, dict):
        return {key: "[REDACTED]" if _SECRET_KEY.search(str(key)) else redact(item)
                for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str):
        return _QUERY_SECRET.sub(r"\1[REDACTED]", value)
    return value


def save_source_response(
    run_dir: Path, run_id: str, provider: str, tool: str, params: dict, response: object,
) -> dict:
    """Write one immutable sanitized response and return its ledger record."""
    safe_tool = re.sub(r"[^a-zA-Z0-9_-]", "_", tool)
    relative = Path("raw") / provider / f"{safe_tool}-{uuid4().hex[:12]}.json"
    target = run_dir / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    observed_at = datetime.now(timezone.utc).isoformat()
    document = {
        "run_id": run_id,
        "provider": provider,
        "tool": tool,
        "params": redact(params),
        "observed_at": observed_at,
        "response": redact(response),
    }
    encoded = (json.dumps(document, ensure_ascii=False, separators=(",", ":"), default=str) + "\n").encode("utf-8")
    target.write_bytes(encoded)
    return {
        "provider": provider,
        "tool": tool,
        "params": document["params"],
        "observed_at": observed_at,
        "file": relative.as_posix(),
        "sha256": hashlib.sha256(encoded).hexdigest(),
    }
