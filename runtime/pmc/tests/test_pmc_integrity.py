import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "build_real_snapshot.py"
SPEC = importlib.util.spec_from_file_location("pmc_build_integrity", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def export_fixture(as_of="2026-10-20"):
    return {
        "as_of": as_of,
        "tools": {
            "erp_listing": {"response": {"data": {"data": {"list": [
                {"store_id": 1, "asin": "B000000001", "local_sku": "SKU-A", "msku": "MSKU-A",
                 "status": 1, "local_name": "测试品", "afn_fulfillable_quantity": 9,
                 "thirty_volume": 30, "thirty_amount": 300, "price": 10},
            ]}}}},
            "get_fba_stock_list": {"response": {"data": {"list": [
                {"sid": 1, "asin": "B000000001", "afn_fulfillable_quantity": 20,
                 "afn_inbound_shipped_quantity": 30, "afn_inbound_receiving_quantity": 3,
                 "inv_age_91_to_180_days": 0, "inv_age_181_to_270_days": 0,
                 "inv_age_271_to_365_days": 0, "inv_age_365_plus_days": 0},
            ]}}},
            "query_fba_valid_list": {"response": {"data": {"data": {"list": [
                {"displayInfo": {"asin": "B000000001", "daysPurchase": 28,
                                 "productList": [{"sku": "SKU-WRONG"}]},
                 "basicInfo": {"relationListing": [{"storeId": 2, "asin": "B000000001"}]},
                 "amazonQuantityInfo": {"afnFulfillableQuantity": 999},
                 "scmQuantityInfo": {"scQuantityLocalValid": 999},
                 "salesInfo": {"salesTotal14": 50, "salesTotal30": 100, "salesTotal60": 200}},
            ]}}}},
            "platform_v2_page_list": {"response": {"data": {"data": {"statisticsList": []}}}},
            "query_product_performance_asin_lists": {"response": {"data": {"data": {"list": [
                {"asin": "B000000001", "sids": [1], "rdate": "2026-10-19", "volume": 2,
                 "afn_fulfillable_quantity": 4, "afn_inbound_receiving_quantity": 0},
            ]}}}},
            "settings_message_inventory_list": {"response": {"data": {"data": {"total": 0}}}},
            "analytics_show_product_list": {"response": {"data": {"code": 0}}},
        },
    }


class PmcIntegrityTests(unittest.TestCase):
    def build(self, data):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "export.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            return MODULE.build_snapshot(path)

    def test_as_of_is_required_not_wall_clock_fallback(self):
        data = export_fixture()
        del data["as_of"]
        with self.assertRaises(ValueError):
            self.build(data)

    def test_query_from_other_store_never_joins_same_asin(self):
        record = self.build(export_fixture())["records"][0]
        self.assertEqual(record["storeId"], "1")
        self.assertEqual(record["sourceAvailable"], 0)
        self.assertEqual(record["sku"], "SKU-A")
        self.assertFalse(record["completenessFlags"]["replenishmentRecord"])

    def test_current_fba_read_overrides_historical_daily_stock(self):
        record = self.build(export_fixture())["records"][0]
        self.assertEqual(record["fbaAvailable"], 20)
        self.assertEqual(record["history"][-2]["fbaSellable"], 4)
        self.assertEqual(record["fbaInboundLive"], 30)
        self.assertEqual(record["inventoryLayers"]["receiving"], 3)

    def test_invalid_scenarios_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "scenarios.json"
            path.write_text("not JSON", encoding="utf-8")
            with self.assertRaises(ValueError):
                MODULE.load_scenarios(path)

    def test_shipment_without_identity_does_not_confirm_eta(self):
        rows = [{"店铺": "济桓-UK", "货件状态": "SHIPPED", "ASIN": "B000000001",
                 "已发货": 20, "签收量": 0, "送达时段(结束时间)": "2026-11-01"}]
        inbound, _, _ = MODULE.shipments_from_rows(rows, "2026-10-20", "fixture.xlsx")
        self.assertFalse(inbound[("济桓-UK", "B000000001")][0]["confirmed"])

    def test_workbook_uses_sheet_with_asin_status_and_eta_not_named_detail_sheet(self):
        from openpyxl import Workbook

        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "shipments.xlsx"
            workbook = Workbook()
            summary = workbook.active
            summary.title = "货件概览"
            summary.append(["货件单号", "店铺", "货件状态", "ASIN", "送达时段(结束时间)", "已发货", "签收量"])
            summary.append(["FBA-1", "济桓-UK", "SHIPPED", "B000000001", "2026-11-01", 20, 0])
            detail = workbook.create_sheet("货件详情")
            detail.append(["货件单号", "店铺", "SKU", "申报量"])
            detail.append(["FBA-1", "济桓-UK", "SKU-A", 20])
            workbook.save(path)
            inbound, _, metadata = MODULE.load_shipments(path, "2026-10-20")
            self.assertEqual(metadata["activeRows"], 1)
            self.assertEqual(inbound[("济桓-UK", "B000000001")][0]["qty"], 20)

    def test_blank_shipment_fields_do_not_inherit_previous_eta(self):
        rows = [
            {"货件单号": "FBA-1", "店铺": "济桓-UK", "货件状态": "SHIPPED",
             "ASIN": "B000000001", "送达时段(结束时间)": "2026-11-01", "已发货": 20},
            {"货件单号": "FBA-2", "店铺": "济桓-UK", "货件状态": "SHIPPED",
             "ASIN": "B000000002", "送达时段(结束时间)": None, "已发货": 20},
        ]
        inbound, _, _ = MODULE.shipments_from_rows(rows, "2026-10-20", "fixture.xlsx")
        self.assertFalse(inbound[("济桓-UK", "B000000002")][0]["confirmed"])


if __name__ == "__main__":
    unittest.main()
