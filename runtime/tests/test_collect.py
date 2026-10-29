import json

import pytest

from b_ops.collect.lingxing import LingxingClient, LingxingError, extract_data, collect_pages
from b_ops.collect.sif import SifClient, SifError, SifReadPacer
from b_ops.collect.transport import JsonRpcHttp, McpTransportError, unpack_rpc
from b_ops.collect.refresh import _sif_terms
from b_ops.collect import refresh


def _mcp(value):
    return {"result": {"content": [{"type": "text", "text": json.dumps(value)}]}}


def test_lingxing_search_blocks_write_tool_before_action():
    calls = []

    def post(method, args):
        calls.append((method, args))
        return _mcp({"code": 1, "data": {"toolType": "write"}})

    client = LingxingClient("https://example.invalid/mcp", "fake", post=post)
    with pytest.raises(LingxingError, match="non-read"):
        client.read("danger", {})
    assert [item[1]["name"] for item in calls] == ["search"]


def test_lingxing_nested_business_failure_rejected():
    def post(method, args):
        if method == "search":
            return _mcp({"code": 1, "data": {"toolType": "read"}})
        return _mcp({"code": 0, "msg": "permission denied"})

    with pytest.raises(LingxingError, match="business"):
        LingxingClient("https://example.invalid/mcp", "fake", post=post).read("x", {})


def test_page_collector_rejects_incomplete_report():
    class Stub:
        def read(self, tool, params):
            return {"code": 1, "data": {"list": [{"asin": "B012345678"}], "total": 2}}

    with pytest.raises(LingxingError, match="duplicate|incomplete"):
        collect_pages(Stub(), "listing", {}, rows_key="list", total_key="total", size=2)


def test_page_collector_advances_by_actual_returned_rows_when_server_caps_page():
    seen = []

    class Stub:
        def read(self, tool, params):
            seen.append(params["offset"])
            rows = [{"id": index} for index in range(params["offset"], min(params["offset"] + 2, 5))]
            return {"code": 1, "data": {"list": rows, "total": 5}}

    assert len(collect_pages(Stub(), "listing", {}, rows_key="list", total_key="total", size=5)) == 5
    assert seen == [0, 2, 4]


def test_sif_response_error_is_not_data():
    client = SifClient("https://example.invalid/mcp", "fake", post=lambda method, args: _mcp({"error": "bad"}))
    with pytest.raises(SifError):
        client.call("market_get_asin_profile", {"asins": ["B012345678"]})


def test_sif_asin_signals_use_real_top_keywords_array():
    assert _sif_terms({'top_keywords':[{'keyword':'kids scissors','organic_rank':12}]}) == [
        {'keyword':'kids scissors','organic_rank':12}]


def test_sif_signal_market_fields_keep_estimates_distinct_from_actual_ad_results():
    result=refresh.signal_market_fields({'traffic_share':.0525,'natural_ratio':.16,
        'top3_click_share':.35,'top3_conversion_share':.27,'cpc_median':.17,
        'contri_change':.0449,'keyword_health':'core'})
    assert result=={'sif_traffic_share':.0525,'sif_natural_ratio':.16,
        'sif_top3_click_share':.35,'sif_top3_conversion_share':.27,'sif_cpc_median':.17}
    assert refresh.signal_market_fields({'traffic_share':1.4,'natural_ratio':-1,'cpc_median':'bad'})=={
        'sif_traffic_share':None,'sif_natural_ratio':None,
        'sif_top3_click_share':None,'sif_top3_conversion_share':None,'sif_cpc_median':None}


def test_sif_http_status_is_diagnostic_without_exposing_credential(monkeypatch):
    from urllib.error import HTTPError
    from b_ops.collect import transport

    def rate_limited(req, timeout):
        raise HTTPError(req.full_url, 429, "too many requests", {}, None)

    monkeypatch.setattr(transport.request, "urlopen", rate_limited)
    connection = JsonRpcHttp("https://example.invalid/mcp", "fake-secret-credential",
                             provider="sif")
    with pytest.raises(McpTransportError) as captured:
        connection.post("tools/call", {"name": "market_get_asin_keyword_signals", "arguments": {}})
    assert captured.value.status_code == 429
    assert "429" in str(captured.value)
    assert "fake-secret-credential" not in str(captured.value)


def test_rpc_error_code_is_preserved_without_echoing_remote_message():
    with pytest.raises(McpTransportError) as captured:
        unpack_rpc({"error": {"code": -32001, "message": "remote detail may contain a key"}})
    assert captured.value.rpc_code == -32001
    assert "remote detail" not in str(captured.value)


def test_sif_read_only_tool_recovers_once_with_a_fresh_mcp_session():
    from types import SimpleNamespace

    calls = []

    def post(method, params):
        calls.append(method)
        if method == "tools/call" and calls.count("tools/call") == 1:
            return {"result": {"isError": True, "content": [{"type": "text", "text": "session expired"}]}}
        if method == "tools/call":
            return _mcp({"top_keywords": [{"keyword": "kids scissors"}]})
        return {"result": {}}

    client = SifClient("https://example.invalid/mcp", "fake", post=post)
    client.transport = SimpleNamespace(session_id="expired-session")
    client.initialized = True
    result = client.call("market_get_asin_keyword_signals", {"asin": "B012345678"})
    assert len(result["top_keywords"]) == 1
    assert client.transport.session_id is None
    assert calls == ["tools/call", "initialize", "notifications/initialized", "tools/call"]


def test_sif_tool_error_reports_a_safe_rate_hint_without_remote_text():
    response = {"result": {"isError": True, "content": [
        {"type": "text", "text": "访问过于频繁，请稍后重试 secret-key=private-value"}]}}
    with pytest.raises(McpTransportError) as captured:
        unpack_rpc(response)
    assert captured.value.error_hint == "rate_limit"
    assert "private-value" not in str(captured.value)


def test_sif_pacer_caps_calls_in_rolling_window():
    now = [0.0]
    slept = []

    def sleep(seconds):
        slept.append(seconds)
        now[0] += seconds

    pacer = SifReadPacer(capacity=2, window_seconds=60, clock=lambda: now[0], sleeper=sleep)
    pacer.before_call()
    now[0] = 1
    pacer.before_call()
    now[0] = 2
    pacer.before_call()
    assert slept == [pytest.approx(58.01)]


def test_sif_rate_limited_read_waits_and_retries_without_credential_leak():
    calls = []
    waits = []

    def post(method, params):
        calls.append(method)
        if len(calls) == 1:
            return {"result": {"isError": True, "content": [
                {"type": "text", "text": "访问过于频繁 secret-key=private-value"}]}}
        return _mcp({"top_keywords": [{"keyword": "kids scissors"}]})

    client = SifClient("https://example.invalid/mcp", "fake", post=post)
    client.transport = type("Transport", (), {"session_id": "existing"})()
    client.initialized = True
    client.pacer = SifReadPacer(clock=lambda: 0.0, sleeper=waits.append)
    result = client.call("market_get_asin_keyword_signals", {"asin": "B012345678"})
    assert len(result["top_keywords"]) == 1
    assert calls == ["tools/call", "tools/call"]
    assert waits == [65]


def test_sif_rate_retry_is_bounded_and_quota_error_is_not_waited_out():
    calls = []
    waits = []

    def limited(method, params):
        calls.append(method)
        return {"result": {"isError": True, "content": [
            {"type": "text", "text": "请求过于频繁"}]}}

    client = SifClient("https://example.invalid/mcp", "fake", post=limited)
    client.transport = type("Transport", (), {"session_id": "existing"})()
    client.initialized = True
    client.pacer = SifReadPacer(clock=lambda: 0.0, sleeper=waits.append)
    with pytest.raises(SifError) as captured:
        client.call("market_get_asin_keyword_signals", {"asin": "B012345678"})
    assert captured.value.error_hint == "rate_limit"
    assert calls == ["tools/call"] * 3
    assert waits == [65, 65]

    quota_calls = []

    def quota_post(method, params):
        quota_calls.append(method)
        return {"result": {"isError": True, "content": [{"type": "text", "text": "配额已用尽"}]}}

    quota = SifClient("https://example.invalid/mcp", "fake", post=quota_post)
    quota.transport = type("Transport", (), {"session_id": "existing"})()
    quota.initialized = True
    quota.pacer = SifReadPacer(clock=lambda: 0.0, sleeper=waits.append)
    with pytest.raises(SifError) as quota_error:
        quota.call("market_get_asin_keyword_signals", {"asin": "B012345678"})
    assert quota_error.value.error_hint == "quota"
    assert quota_calls == ["tools/call"]
    assert waits == [65, 65]
