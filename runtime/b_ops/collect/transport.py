"""Small streamable-HTTP JSON-RPC transport; no secret or response body in errors."""

from __future__ import annotations

import json
import hashlib
import re
from urllib import parse, request
from urllib.error import HTTPError


class McpTransportError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None,
                 rpc_code: int | None = None, kind: str | None = None,
                 error_hint: str | None = None, error_fingerprint: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.rpc_code = rpc_code
        self.kind = kind
        self.error_hint = error_hint
        self.error_fingerprint = error_fingerprint


def _tool_error_metadata(result: dict) -> tuple[str, str]:
    detail = " ".join(str(item.get("text") or "") for item in result.get("content", [])
                      if isinstance(item, dict) and item.get("type") == "text")
    lower = detail.casefold()
    categories = (
        ("rate_limit", r"too many|rate.?limit|throttl|频繁|限流|超频|请求过多|次数限制"),
        ("quota", r"quota|credit|余额不足|配额|额度|次数用尽"),
        ("authorization", r"unauthori|forbidden|permission|invalid.key|认证|未授权|无权限"),
        ("session", r"session|会话|expired|过期"),
        ("timeout", r"timeout|timed out|超时"),
        ("no_data", r"no data|not found|暂无数据|无数据"),
        ("upstream", r"failed to respond|upstream|internal[_ ]error|server error|服务器错误|服务异常"),
    )
    hint = next((name for name, pattern in categories if re.search(pattern, lower)), "unknown")
    return hint, hashlib.sha256(detail.encode("utf-8")).hexdigest()[:12]


def unpack_rpc(value: dict) -> dict:
    if "error" in value:
        error = value["error"]
        code = error.get("code") if isinstance(error, dict) else None
        code = code if isinstance(code, int) else None
        raise McpTransportError(f"MCP JSON-RPC error {code if code is not None else 'unknown'}",
                                rpc_code=code, kind="rpc_error")
    result = value.get("result", value)
    if result.get("isError"):
        hint, fingerprint = _tool_error_metadata(result)
        raise McpTransportError("MCP tool returned an error", kind="tool_error",
                                error_hint=hint, error_fingerprint=fingerprint)
    return result


def content_object(result: dict):
    if isinstance(result.get("structuredContent"), (dict, list)):
        return result["structuredContent"]
    for item in result.get("content", []):
        if item.get("type") == "text" and isinstance(item.get("text"), str):
            try:
                return json.loads(item["text"])
            except json.JSONDecodeError:
                continue
    raise McpTransportError("MCP result has no JSON content", kind="no_json_content")


class JsonRpcHttp:
    def __init__(self, url: str, key: str, *, provider: str, timeout: int = 90):
        if not url or not key:
            raise ValueError(f"{provider} endpoint and credential are required")
        self.url, self.key, self.provider, self.timeout = url, key, provider, timeout
        self.session_id = None
        self.seq = 0

    def post(self, method: str, params: dict) -> dict:
        self.seq += 1
        payload = {"jsonrpc": "2.0", "method": method, "params": params}
        if not method.startswith("notifications/"):
            payload["id"] = self.seq
        headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        url = self.url
        if self.provider == "lingxing":
            headers["X-Mcp-Key"] = self.key
        else:
            headers["secret-key"] = self.key
            separator = "&" if "?" in url else "?"
            url += separator + "secret-key=" + parse.quote(self.key, safe="")
            if self.session_id:
                headers["Mcp-Session-Id"] = self.session_id
        req = request.Request(url, data=json.dumps(payload, ensure_ascii=False).encode(), headers=headers, method="POST")
        try:
            with request.urlopen(req, timeout=self.timeout) as response:
                self.session_id = response.headers.get("Mcp-Session-Id", self.session_id)
                body = response.read().decode("utf-8")
        except HTTPError as exc:
            # HTTPError's URL can contain the SIF key. Preserve only the code.
            raise McpTransportError(f"{self.provider} HTTP {exc.code}", status_code=exc.code,
                                    kind="http_error") from None
        except Exception as exc:
            raise McpTransportError(f"{self.provider} transport failed: {type(exc).__name__}",
                                    kind="network_error") from None
        candidates = []
        for line in body.splitlines():
            candidate = line[5:].strip() if line.startswith("data:") else line.strip()
            if not candidate.startswith("{"):
                continue
            try:
                candidates.append(json.loads(candidate))
            except json.JSONDecodeError:
                pass
        if not candidates and method.startswith("notifications/"):
            return {"result": {}}
        if not candidates:
            raise McpTransportError(f"{self.provider} response was not JSON-RPC")
        return candidates[-1]
