import copy
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from b_ops.collect.lingxing_supply_details import (
    SCHEMA, collect_details, apply_details, reconcile_fba, SupplyError,
    FBA_PATH, PRODUCT_PATH, PURCHASE_PATH, RECEIPT_PATH,
)

DAY = "2026-10-29"


def snapshot():
    return {"metadata": {"asOf": DAY}, "records": [{"storeId": "1", "asin": "B000000001", "sku": "SKU", "skus": ["SKU"],
        "inventoryLayers": {"local": 40, "procurementOpen": 99}, "procurementOpen": 99, "cartonQty": 0}]}


def purchase(**updates):
    row = dict(sid="1", sku="SKU", order_sn="PO1", item_id="10", status="2", arrival_status="2", deleted="0",
        ordered_qty=100, pending_qty=60, stocked_qty=20, returned_qty=0, exchanged_qty=0, expected_date="2026-11-02", carton_qty=12)
    return {**row, **updates}


def receipt(**updates):
    return {**dict(sid="1", sku="SKU", order_sn="CR1", item_id="20", purchase_order="PO1", purchase_item_id="10",
        status="40", actual_qty=40, actual_time="2026-10-23 18:50:10", expected_date="2026-11-03"), **updates}


def details():
    return dict(schema=SCHEMA, as_of=DAY, window_start="2026-01-01", generated_at="now", errors={},
        states={k:"complete_window" for k in ["purchases", "receipts", "products", "shipments"]},
        purchases=[purchase()], receipts=[receipt()], shipments=[],
        products=[dict(sku="SKU", carton_qty=12, moq=100, moq_state="consistent", quotes=[], components=[], state="verified")])


def test_receipts_are_not_stock_or_future_supply_and_reapplication_is_idempotent():
    s, d = snapshot(), details()
    # Duplicate delivery is counted once, despite receipt time and estimated date differing.
    d["receipts"] *= 2
    out = apply_details(s, d, allowed_sids=[1])
    r = out["records"][0]
    assert r["inventoryLayers"]["local"] == 40
    assert r["procurementOpen"] == 60
    assert r["purchaseEvidence"]["items"][0]["actual_received_in_window"] == 40
    assert r["procurementLots"] == [{"id":"PO1:10", "qty":60, "date":"2026-11-02"}]
    assert r["cartonQty"] == 12 and r["moq"] == 100
    assert apply_details(out, d, allowed_sids=[1]) == out
    assert s["records"][0]["procurementOpen"] == 99


@pytest.mark.parametrize("updates,remaining", [
    ({"status":"9", "pending_qty":0}, 0), ({"status":"-1"}, 0), ({"deleted":"1"},0),
    ({"status":"124"},0), ({"status":"1"},0), ({"status":"3"},0), ({"returned_qty":1},None), ({"exchanged_qty":1},None),
    ({"pending_qty":90},None), ({"arrival_status":"3"},None), ({"pending_qty":None},None),
])
def test_closed_or_unreconciled_purchase_never_creates_future_supply(updates, remaining):
    d=details();d["purchases"]=[purchase(**updates)]
    r=apply_details(snapshot(),d,allowed_sids=[1])["records"][0]
    assert r["procurementLots"] == []
    assert r["purchaseEvidence"]["items"][0]["remaining_qty"] == remaining


def test_shared_sku_does_not_allocate_by_sales_or_duplicate_aggregate():
    s=snapshot();s["records"].append({**copy.deepcopy(s["records"][0]),"asin":"B000000002","units30":9999})
    out=apply_details(s,details(),allowed_sids=[1])
    assert all(r["procurementOpen"] is None and not r["procurementLots"] for r in out["records"])
    assert len(out["metadata"]["supplyDetails"]["ledger"]["purchases"]) == 1


def test_component_receipts_do_not_become_finished_goods():
    d=details();d["products"][0]["components"]=[{"sku":"PART","quantity":2}]
    d["purchases"]=[purchase(sku="PART")];d["receipts"]=[receipt(sku="PART")]
    r=apply_details(snapshot(),d,allowed_sids=[1])["records"][0]
    assert len(r["purchaseEvidence"]["component_items"]) == 1
    assert len(r["purchaseEvidence"]["receipts"]) == 1
    assert r["procurementOpen"] == 0 and not r["procurementLots"]


def test_mismatch_and_conflicting_duplicate_fail_closed():
    d=details();d["receipts"]=[receipt(sku="WRONG")]
    out=apply_details(snapshot(),d,allowed_sids=[1])
    assert out["records"][0]["procurementOpen"] is None
    assert out["metadata"]["supplyDetails"]["ledger"]["receipts"][0]["join_state"] == "shop_or_sku_conflict"
    d=details();d["receipts"].append(receipt(actual_qty=50))
    with pytest.raises(SupplyError,match="DUPLICATE"):
        apply_details(snapshot(),d,allowed_sids=[1])
    d=details();d["receipts"][0]["sid"]="2"
    with pytest.raises(SupplyError,match="SCOPE"):
        apply_details(snapshot(),d,allowed_sids=[1])


def test_existing_manual_rule_not_overwritten_and_zero_is_not_positive_moq():
    s=snapshot();s["records"][0].update(cartonQty=24,moq=200)
    r=apply_details(s,details(),allowed_sids=[1])["records"][0]
    assert (r["cartonQty"],r["moq"]) == (24,200)
    d=details();d["products"][0].update(carton_qty=0,moq=0)
    r=apply_details(snapshot(),d,allowed_sids=[1])["records"][0]
    assert r["cartonQty"] == 0 and "moq" not in r


def read_fixture(path, body):
    if path == PRODUCT_PATH:
        return {"code":0,"data":{"sku":"SKU","cg_box_pcs":12,"supplier_quote":[{"supplier_id":1,"quotes":[{"id":2,"step_prices":[{"moq":100},{"moq":500}]}]}]}}
    return {"code":0,"data":[] if path==PURCHASE_PATH else {"list":[],"total":0},"total":0}


def test_collector_pagination_filters_foreign_shops_before_publication():
    def read(path, body):
        if path==PURCHASE_PATH:
            i=body["offset"]
            return {"code":0,"total":2,"data":[{"order_sn":f"PO{i}","item_list":[{"id":i+1,"sku":"SKU","sid":1 if i else 2}]}]}
        return read_fixture(path,body)
    d=collect_details(read,snapshot=snapshot(),allowed_sids=[1],start_date="2026-01-01")
    assert d["states"]["purchases"] == "complete_window"
    assert len(d["purchases"]) == 1 and d["purchases"][0]["sid"] == "1"
    assert d["products"][0]["moq"] == 100


def test_overlapping_pages_are_failed_not_inflated():
    def read(path, body):
        if path==PURCHASE_PATH:
            return {"code":0,"total":2,"data":[{"order_sn":"PO1","item_list":[]}]}
        return read_fixture(path,body)
    d=collect_details(read,snapshot=snapshot(),allowed_sids=[1],start_date="2026-01-01")
    assert d["states"]["purchases"] == "failed" and d["purchases"] == []
    assert d["errors"]["purchases"] == "API_PAGE_OVERLAP"


def test_scope_and_budget_before_network():
    with pytest.raises(SupplyError,match="SCOPE"):
        collect_details(lambda *_:pytest.fail(),snapshot=snapshot(),allowed_sids=[2],start_date="2026-01-01")
    d=collect_details(read_fixture,snapshot=snapshot(),allowed_sids=[1],start_date="2026-01-01",max_calls=1)
    assert d["calls"] == 1 and d["states"]["purchases"] == "failed"


def test_fba_declared_and_locally_shipped_are_not_the_same_quantity():
    d=details();d["shipments"]=[dict(sid="1",asin="B000000001",shipment_id="FBA1",status="READY_TO_SHIP",local_shipped_qty=0,received_qty=0,declared_qty=504)]
    supply={"as_of":DAY,"records":[{"sid":"1","asin":"B000000001","state":"verified","items":[{"shipment_id":"FBA1","state":"verified","quantity":504}]}]}
    out=reconcile_fba(supply,d,allowed_sids=[1])
    assert out["records"][0]["items"][0]["state"] == "waiting_dispatch"
    d["shipments"][0].update(status="IN_TRANSIT",local_shipped_qty=100,received_qty=20)
    out=reconcile_fba(supply,d,allowed_sids=[1])
    assert out["records"][0]["items"][0]["quantity"] == 80
    assert reconcile_fba(out,d,allowed_sids=[1]) == out


def test_refresh_replaces_api_defaults_but_keeps_personal_rules():
    first=apply_details(snapshot(),details(),allowed_sids=[1])
    changed=details();changed['products'][0].update(carton_qty=24,moq=200)
    second=apply_details(first,changed,allowed_sids=[1])
    assert second['records'][0]['cartonQty']==24 and second['records'][0]['moq']==200
    changed['products'][0].update(carton_qty=0,moq=None)
    third=apply_details(second,changed,allowed_sids=[1])
    assert third['records'][0]['cartonQty']==0 and 'moq' not in third['records'][0]


def test_failed_receipt_collection_is_unknown_not_zero_received():
    d=details();d['states']['receipts']='failed';d['receipts']=[]
    r=apply_details(snapshot(),d,allowed_sids=[1])['records'][0]
    assert r['purchaseEvidence']['items'][0]['actual_received_in_window'] is None
    assert r['procurementOpen'] is None and r['procurementLots']==[]


@pytest.mark.parametrize("updates", [{"actual_time":None},{"actual_time":"2026-11-01 12:00:00"},{"actual_qty":None},{"status":"10"}])
def test_invalid_receipt_is_not_silently_zero(updates):
    d=details();d['receipts']=[receipt(**updates)]
    row=apply_details(snapshot(),d,allowed_sids=[1])['records'][0]
    assert row['purchaseEvidence']['items'][0]['actual_received_in_window'] is None
    assert row['procurementOpen'] is None and not row['procurementLots']


def test_failed_product_refresh_clears_api_defaults_but_preserves_manual_rules():
    old=apply_details(snapshot(),details(),allowed_sids=[1])
    d=details();d['products']=[{'sku':'SKU','state':'failed'}];d['states']['products']='partial'
    new=apply_details(old,d,allowed_sids=[1])['records'][0]
    assert new['cartonQty']==0 and 'moq' not in new
    manual=snapshot();manual['records'][0].update(cartonQty=24,cartonSource='manual',moq=500)
    new=apply_details(manual,d,allowed_sids=[1])['records'][0]
    assert new['cartonQty']==24 and new['moq']==500
