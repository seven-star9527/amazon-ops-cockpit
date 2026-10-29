import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from b_ops.collect.lingxing_supply import collect_supply, apply_supply, SupplyError, SOURCE_PATH, DISPATCH_PATH

ASIN = "B000000001"
DAY = "2026-10-29"


def source(rows=None):
    return {"code": 0, "data": {"source_list": rows if rows is not None else [
        {"type": 2, "quantity": 10, "remark": {"shipment_id": "FBA1"}, "amazon_sale_date": "2026-12-01"}]}}


def dispatch(eta="2026-11-01", sid=1, asin=ASIN, sn="SP1", status=1):
    return {"shipment_sn": sn, "expected_arrival_date": eta, "status": status,
            "eta_date": "2026-10-30", "relate_list": [{"sid": sid, "asin": asin, "shipment_id": "FBA1"}]}


def collect(src=None, orders=None, **kwargs):
    def read(path, body):
        if path == SOURCE_PATH:
            assert body == {"sid": 1, "asin": ASIN, "type": "2"}
            return src if src is not None else source()
        assert path == DISPATCH_PATH and body["sids"] == "1" and body["search_value"] == "FBA1"
        return {"code": 0, "data": {"list": orders if orders is not None else [dispatch()]}}
    return collect_supply(read, targets=[("1", ASIN)], allowed_sids=["1"], as_of=DAY, **kwargs)


def snapshot():
    return {"metadata": {"asOf": DAY}, "records": [{"storeId": "1", "asin": ASIN,
        "inventoryLayers": {"shippedRaw": 15}, "inbound": [], "evidence": [],
        "completenessFlags": {"etaEvidence": False, "skuMapping": True}, "dataCompleteness": 50}]}


def test_uses_only_fba_eta_and_preserves_stock_and_residual():
    s = snapshot()
    out = apply_supply(s, collect(), allowed_sids=[1])
    record = out["records"][0]
    assert record["inbound"][0]["date"] == "2026-11-01"
    assert record["inbound"][0]["confirmed"] is True
    assert record["inbound"][1]["qty"] == 5 and record["inbound"][1]["date"] is None
    assert record["inventoryLayers"] == s["records"][0]["inventoryLayers"]
    assert record["dataCompleteness"] == 100
    assert s["records"][0]["inbound"] == []
    assert apply_supply(out, collect(), allowed_sids=[1])["records"] == out["records"]


@pytest.mark.parametrize("orders,state", [
    ([dispatch(eta="")], "missing_eta"), ([dispatch(eta="2026-10-01")], "overdue_eta"),
    ([dispatch(sid=2)], "unmatched_dispatch"), ([dispatch(asin="B000000002")], "unmatched_dispatch"),
    ([dispatch(status=3)], "void"),
    ([dispatch(status=-1)], "waiting_pick"), ([dispatch(status=0)], "waiting_dispatch"),
    ([dispatch(status=2)], "completed"),
    ([dispatch(), dispatch(sn="SP2")], "ambiguous_dispatch"),
])
def test_incomplete_or_cross_store_evidence_never_confirms(orders, state):
    result = collect(orders=orders)
    assert result["records"][0]["items"][0]["state"] == state
    out = apply_supply(snapshot(), result, allowed_sids=[1])
    assert out["records"][0]["inbound"][0]["confirmed"] is False


def test_denies_scope_before_any_network():
    with pytest.raises(SupplyError, match="STORE_SCOPE_DENIED"):
        collect_supply(lambda *_: pytest.fail("network must not run"), targets=[(2, ASIN)], allowed_sids=[1], as_of=DAY)


@pytest.mark.parametrize("src", [
    {"code": 1, "data": {}}, {"code": 0, "data": {}},
    source(source()["data"]["source_list"] * 2),
    source([{"type": 2, "quantity": None, "remark": {"shipment_id": "FBA1"}}]),
])
def test_failure_does_not_replace_prior_supply(src):
    result = collect(src=src)
    assert result["records"][0]["state"] == "failed"
    s = snapshot(); s["records"][0]["inbound"] = [{"prior": True}]
    assert apply_supply(s, result, allowed_sids=[1])["records"] == s["records"]


def test_budget_and_transport_errors_remain_partial_without_retry_or_secrets():
    result = collect(max_calls=1)
    assert result["calls"] == 1 and result["records"][0]["state"] == "partial"
    assert result["records"][0]["errors"] == ["CALL_BUDGET_EXHAUSTED"]
    def broken(*_):
        raise RuntimeError("secret=do-not-emit")
    result = collect_supply(broken, targets=[(1, ASIN)], allowed_sids=[1], as_of=DAY)
    assert "do-not-emit" not in str(result)
    assert result["calls"] == 1


def test_same_day_and_unique_scope_required():
    result = collect()
    result["as_of"] = "2026-10-28"
    with pytest.raises(SupplyError, match="DATE_OR_SCHEMA"):
        apply_supply(snapshot(), result, allowed_sids=[1])
    result = collect(); result["records"] *= 2
    with pytest.raises(SupplyError, match="DUPLICATE"):
        apply_supply(snapshot(), result, allowed_sids=[1])


def test_empty_source_is_known_empty_not_query_failure():
    result = collect(src=source([]))
    assert result["calls"] == 1 and result["records"][0]["state"] == "verified"
    out = apply_supply(snapshot(), result, allowed_sids=[1])
    assert out["records"][0]["inbound"][0]["qty"] == 15
    assert out["records"][0]["inbound"][0]["confirmed"] is False


def test_source_nonpaging_total_zero_is_not_a_page_count():
    src = source(); src["total"] = 0
    assert collect(src=src)["records"][0]["state"] == "verified"


def test_dispatch_incomplete_page_is_not_silently_accepted():
    def read(path, body):
        return source() if path == SOURCE_PATH else {"code": 0, "data": {"list": [dispatch()], "total": 101}}
    result = collect_supply(read, targets=[(1, ASIN)], allowed_sids=[1], as_of=DAY)
    assert result["records"][0]["items"][0]["state"] == "query_failed"
    assert "API_INCOMPLETE_PAGE" in result["records"][0]["errors"]


def test_rejects_product_not_in_snapshot_and_unauthorized_snapshot():
    result = collect()
    result["records"][0]["asin"] = "B000000002"
    with pytest.raises(SupplyError, match="UNKNOWN_PRODUCT"):
        apply_supply(snapshot(), result, allowed_sids=[1])
    s = snapshot(); s["records"].append({"storeId": "2", "asin": ASIN})
    with pytest.raises(SupplyError, match="SNAPSHOT_SCOPE_DENIED"):
        apply_supply(s, collect(), allowed_sids=[1])


def test_zero_current_transit_never_confirms_old_positive_shipment():
    s=snapshot();s['records'][0]['inventoryLayers']['shippedRaw']=0
    out=apply_supply(s,collect(),allowed_sids=[1])
    assert not any(i['confirmed'] for i in out['records'][0]['inbound'])
    assert out['metadata']['scope']['etaCoveredRows']==0


def test_planned_shipment_absent_from_source_still_gets_exact_dispatch_link():
    def read(path,body):
        return source([]) if path==SOURCE_PATH else {'code':0,'data':{'list':[dispatch(status=-1)],'total':1}}
    result=collect_supply(read,targets=[('1',ASIN)],allowed_sids=[1],as_of=DAY,
        shipment_rows=[{'sid':'1','asin':ASIN,'shipment_id':'FBA1','status':'READY_TO_SHIP','local_shipped_qty':0,'received_qty':0}])
    item=result['records'][0]['items'][0]
    assert item['shipment_sn']=='SP1' and item['state']=='waiting_pick' and item['quantity']==0


def test_repeated_eta_attachment_preserves_order_of_other_quality_gaps():
    out=apply_supply(snapshot(),collect(orders=[dispatch(eta='')]),allowed_sids=[1])
    out['records'][0]['dataGaps'].append('purchase window incomplete')
    again=apply_supply(out,collect(orders=[dispatch(eta='')]),allowed_sids=[1])
    assert again['records']==out['records']
