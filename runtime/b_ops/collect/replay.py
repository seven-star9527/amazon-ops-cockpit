"""Resume normalization from a same-day B-line MCP read, never from A/old caches."""

from __future__ import annotations

from collections import defaultdict, deque
import hashlib
import json

def _params(params):
    params = dict(params)
    for old in ("topN", "limit", "max_results", "max_competitors"):
        if old in params:
            params.setdefault("pageSize", params.pop(old))
    return params

from pathlib import Path


class ReplayMissing(RuntimeError):
    pass


class ReplayLingxing:
    def __init__(self, run_dir: Path):
        self.source_run_id = Path(run_dir).name
        self.responses = defaultdict(deque)
        raw_dir = Path(run_dir) / "raw" / "lingxing"
        for path in sorted(raw_dir.glob("*.json")):
            doc = json.loads(path.read_text(encoding="utf-8"))
            key = (doc.get("tool"), json.dumps(doc.get("params") or {}, sort_keys=True, ensure_ascii=False))
            self.responses[key].append(doc.get("response"))

    def read(self, tool: str, params: dict) -> dict:
        key = (tool, json.dumps(params, sort_keys=True, ensure_ascii=False))
        if not self.responses[key]:
            raise ReplayMissing(f"No recorded B-line MCP response for {tool}")
        return self.responses[key].popleft()


class ReplaySif:
    def __init__(self, run_dir: Path):
        self.source_run_id = Path(run_dir).name
        self.responses = defaultdict(deque)
        raw_dir = Path(run_dir) / "raw" / "sif"
        for path in sorted(raw_dir.glob("*.json")):
            doc = json.loads(path.read_text(encoding="utf-8"))
            key = (doc.get("tool"), json.dumps(_params(doc.get("params") or {}), sort_keys=True, ensure_ascii=False))
            self.responses[key].append(doc.get("response"))

    def call(self, tool: str, params: dict):
        key = (tool, json.dumps(_params(params), sort_keys=True, ensure_ascii=False))
        if not self.responses[key]:
            raise ReplayMissing(f"No recorded B-line SIF response for {tool}")
        return self.responses[key].popleft()


class ResumeSif(ReplaySif):
    """Reuse exact partial B-line reads, then continue missing calls live.

    The caller must restrict the source to the current day's B-line raw run.
    A fresh run ledger records every reused and new response again.
    """

    transport_state = "same_day_b_raw_resume_live"

    def __init__(self, run_dir: Path, live_client):
        super().__init__(run_dir)
        self.live_client = live_client
        self.replayed_calls = 0
        self.live_calls = 0
        self.last_call_source = None

    def call(self, tool: str, params: dict):
        key = (tool, json.dumps(_params(params), sort_keys=True, ensure_ascii=False))
        if self.responses[key]:
            self.replayed_calls += 1
            self.last_call_source = "replay"
            return self.responses[key][-1]
        result = self.live_client.call(tool, params)
        self.live_calls += 1
        self.last_call_source = "live"
        self.responses[key].append(result)
        return result


class ExtendSif(ResumeSif):
    """Extend a completed, hash-verified same-day B batch with only new SIF calls."""

    transport_state = "same_day_b_complete_extend_live"

    def __init__(self, run_dir: Path, live_client):
        run_dir = Path(run_dir)
        manifest_path = run_dir / "manifest.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ValueError("completed SIF source manifest missing") from exc
        if manifest.get("state") != "complete" or manifest.get("run_id") != run_dir.name:
            raise ValueError("SIF extension requires a complete matching B run")
        recorded = [item for item in manifest.get("source_calls", []) if item.get("provider") == "sif"]
        if not recorded:
            raise ValueError("completed SIF source has no recorded calls")
        for item in recorded:
            relative = Path(str(item.get("file") or ""))
            if (relative.is_absolute() or ".." in relative.parts or
                    relative.parts[:2] != ("raw", "sif")):
                raise ValueError("invalid completed SIF source file")
            data = (run_dir / relative).read_bytes()
            if hashlib.sha256(data).hexdigest() != item.get("sha256"):
                raise ValueError("completed SIF source hash mismatch")
            doc = json.loads(data)
            if (doc.get("run_id") != run_dir.name or doc.get("provider") != "sif" or
                    doc.get("tool") != item.get("tool") or doc.get("params") != item.get("params")):
                raise ValueError("completed SIF source ledger mismatch")
        super().__init__(run_dir, live_client)
