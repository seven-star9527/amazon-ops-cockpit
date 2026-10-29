import json

from b_ops.collect.ledger import save_source_response


def test_source_ledger_redacts_credentials_and_hashes_saved_payload(tmp_path):
    response = {
        "data": [{"asin": "B012345678", "sales": 3}],
        "headers": {"X-Mcp-Key": "FAKE_LX_SECRET_123"},
        "url": "https://mcp.sif.com/mcp?secret-key=FAKE_SIF_SECRET_456",
    }
    record = save_source_response(
        tmp_path, "run-1", "lingxing", "query_product_performance_asin_lists",
        {"page": 1, "secret-key": "FAKE_SIF_SECRET_456"}, response,
    )
    raw = (tmp_path / record["file"]).read_text(encoding="utf-8")
    assert "B012345678" in raw
    assert "FAKE_LX_SECRET_123" not in raw
    assert "FAKE_SIF_SECRET_456" not in raw
    assert record["sha256"]
    assert json.loads(raw)["response"]["data"][0]["sales"] == 3
