"""SIF MCP collector. Weekly demand and rank observations retain their real periods."""

from __future__ import annotations

from collections import deque
import time

from .transport import JsonRpcHttp, McpTransportError, content_object, unpack_rpc


class SifError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None,
                 rpc_code: int | None = None, kind: str | None = None,
                 error_hint: str | None = None, error_fingerprint: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.rpc_code = rpc_code
        self.kind = kind
        self.error_hint = error_hint
        self.error_fingerprint = error_fingerprint


class SifReadPacer:
    """Bound live SIF tool calls to a conservative rolling minute."""

    def __init__(self, *, capacity: int = 20, window_seconds: float = 60,
                 clock=None, sleeper=None):
        self.capacity = capacity
        self.window_seconds = window_seconds
        self.clock = clock or time.monotonic
        self.sleeper = sleeper or time.sleep
        self.calls = deque()

    def before_call(self) -> None:
        while True:
            now = self.clock()
            while self.calls and now - self.calls[0] >= self.window_seconds:
                self.calls.popleft()
            if len(self.calls) < self.capacity:
                self.calls.append(now)
                return
            self.sleeper(max(0.01, self.window_seconds - (now - self.calls[0]) + 0.01))

    def cooldown(self, seconds: float = 65) -> None:
        self.sleeper(seconds)


class SifClient:
    def __init__(self, url: str, key: str, *, post=None):
        self.transport = None if post else JsonRpcHttp(url, key, provider="sif")
        self.post = post or self.transport.post
        self.initialized = False
        self.pacer = SifReadPacer() if self.transport is not None else None

    def initialize(self):
        if self.initialized:
            return
        try:
            unpack_rpc(self.post("initialize", {
                "protocolVersion": "2025-03-26", "capabilities": {},
                "clientInfo": {"name": "amazon-ops-b", "version": "1.0"},
            }))
            self.post("notifications/initialized", {})
        except McpTransportError as exc:
            raise SifError(str(exc), status_code=exc.status_code,
                           rpc_code=exc.rpc_code, kind=exc.kind,
                           error_hint=exc.error_hint,
                           error_fingerprint=exc.error_fingerprint) from None
        self.initialized = True

    def tools(self) -> list[dict]:
        self.initialize()
        try:
            result = unpack_rpc(self.post("tools/list", {}))
        except McpTransportError as exc:
            raise SifError(str(exc), status_code=exc.status_code,
                           rpc_code=exc.rpc_code, kind=exc.kind,
                           error_hint=exc.error_hint,
                           error_fingerprint=exc.error_fingerprint) from None
        return result.get("tools", [])

    def reset_session(self) -> None:
        if self.transport is not None:
            self.transport.session_id = None
            self.initialized = False

    def call(self, tool: str, arguments: dict):
        arguments = dict(arguments)
        for old in ("topN", "limit", "max_results", "max_competitors"):
            if old in arguments:
                arguments.setdefault("pageSize", arguments.pop(old))
        session_retries = 0
        rate_retries = 0
        while True:
            if self.transport is not None:
                self.initialize()
            if self.pacer is not None:
                self.pacer.before_call()
            try:
                value = content_object(unpack_rpc(self.post("tools/call", {"name": tool, "arguments": arguments})))
                if isinstance(value, dict) and ("error" in value or value.get("success") is False):
                    raise SifError(f"SIF tool {tool} returned a business error", kind="business_error")
                return value
            except McpTransportError as exc:
                if ((exc.error_hint == "rate_limit" or exc.status_code == 429)
                        and rate_retries < 2 and self.pacer is not None):
                    rate_retries += 1
                    self.pacer.cooldown()
                    continue
                if (session_retries == 0 and self.transport is not None and exc.kind == "tool_error"
                        and exc.error_hint == "session"
                        and tool.startswith(("market_get_", "ads_get_", "ops_get_"))):
                    session_retries += 1
                    self.reset_session()
                    continue
                raise SifError(str(exc), status_code=exc.status_code,
                               rpc_code=exc.rpc_code, kind=exc.kind,
                               error_hint=exc.error_hint,
                               error_fingerprint=exc.error_fingerprint) from None
