"""Lingxing MCP read-only collector with business and pagination guards."""

from __future__ import annotations

from .transport import JsonRpcHttp, McpTransportError, content_object, unpack_rpc


class LingxingError(RuntimeError):
    pass


def extract_data(value: dict):
    data = value.get("data")
    while isinstance(data, dict) and "code" in data and "data" in data:
        if data.get("code") not in {0, 1} or data.get("success") is False:
            raise LingxingError("nested business failure")
        data = data["data"]
    return data


class LingxingClient:
    def __init__(self, url: str, key: str, *, post=None):
        self.transport = None if post else JsonRpcHttp(url, key, provider="lingxing")
        self.post = post or self.transport.post
        self.verified = set()

    def _call(self, name: str, arguments: dict) -> dict:
        try:
            result = content_object(unpack_rpc(self.post("tools/call", {"name": name, "arguments": arguments})))
        except McpTransportError as exc:
            raise LingxingError(str(exc)) from None
        if not isinstance(result, dict) or result.get("code") != 1 or result.get("success") is False:
            raise LingxingError(f"Lingxing business failure ({arguments.get('toolId', name)})")
        return result

    def read(self, tool: str, params: dict) -> dict:
        if tool not in self.verified:
            definition = extract_data(self._call("search", {"toolId": tool}))
            if not isinstance(definition, dict) or definition.get("toolType") != "read":
                raise LingxingError(f"non-read tool blocked: {tool}")
            self.verified.add(tool)
        return self._call("action", {"toolId": tool, "params": params})

    def write(self, tool: str, params: dict) -> dict:
        """Call an explicitly verified write tool; never used by read collectors."""
        marker = f"write:{tool}"
        if marker not in self.verified:
            definition = extract_data(self._call("search", {"toolId": tool}))
            if not isinstance(definition, dict) or definition.get("toolType") != "write":
                raise LingxingError(f"non-write tool blocked: {tool}")
            self.verified.add(marker)
        return self._call("action", {"toolId": tool, "params": params})


def collect_pages(client: LingxingClient, tool: str, base: dict, *, rows_key: str,
                  total_key: str, size: int = 500, offset_key: str = "offset",
                  length_key: str = "length", max_pages: int = 100) -> list[dict]:
    rows = []
    expected = None
    seen = set()
    for page in range(max_pages):
        cursor = page + 1 if offset_key in {"page", "pageNum"} else len(rows)
        params = {**base, offset_key: cursor, length_key: size}
        data = extract_data(client.read(tool, params))
        if not isinstance(data, dict) or not isinstance(data.get(rows_key), list):
            raise LingxingError(f"{tool} page shape mismatch")
        part = data[rows_key]
        page_total = data.get(total_key)
        if page_total is not None:
            if expected is not None and int(page_total) != expected:
                raise LingxingError(f"{tool} total changed between pages")
            expected = int(page_total)
        for item in part:
            if not isinstance(item, dict):
                raise LingxingError(f"{tool} non-object row")
            marker = str(item)
            if marker in seen:
                raise LingxingError(f"{tool} duplicate row across pages")
            seen.add(marker)
            rows.append(item)
        if not part or (expected is not None and len(rows) >= expected):
            break
        if expected is None and len(part) < size:
            break
    else:
        raise LingxingError(f"{tool} exceeded page bound")
    if expected is not None and len(rows) != expected:
        raise LingxingError(f"{tool} incomplete pages: {len(rows)}/{expected}")
    return rows
