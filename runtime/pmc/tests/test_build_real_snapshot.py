import importlib.util
import sys
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "build_real_snapshot.py"
SPEC = importlib.util.spec_from_file_location("build_real_snapshot", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class BuildRealSnapshotTests(unittest.TestCase):
    def test_aggregate_sales_expand_to_sixty_days_without_changing_total(self):
        history = MODULE.history_from_sales_totals(
            {"salesTotal14": 140, "salesTotal30": 260, "salesTotal60": 500}
        )
        self.assertEqual(len(history), 60)
        self.assertAlmostEqual(sum(history), 500, places=4)
        self.assertGreater(sum(history[-20:]), sum(history[:20]))

    def test_query_record_maps_inventory_sku_and_purchase_days(self):
        query = {
            "displayInfo": {
                "asin": "B0REAL1234",
                "daysPurchase": 36,
                "productList": [{"sku": "LOCAL-SKU", "productName": "测试品"}],
                "storeList": ["店铺"],
                "fbaAgedInfo": {
                    "invAge91To180Days": 4,
                    "invAge181To270Days": 3,
                    "invAge271To365Days": 2,
                    "invAge365PlusDays": 1,
                },
            },
            "basicInfo": {
                "syncTime": "2026-10-15 12:00:00",
                "relationListing": [
                    {"asin": "B0REAL1234", "storeId": 5906, "msku": "MSKU-1", "fnsku": "FNSKU-1"}
                ],
            },
            "amazonQuantityInfo": {"afnFulfillableQuantity": 90, "amazonQuantityShipping": 30},
            "scmQuantityInfo": {
                "scQuantityLocalValid": 50,
                "scQuantityOverseaValid": 20,
                "scQuantityPurchasePlan": 100,
                "scQuantityPurchaseShipping": 40,
            },
            "salesInfo": {"salesTotal14": 140, "salesTotal30": 260, "salesTotal60": 500},
            "suggestInfo": {"estimatedSaleAvgQuantity": 9.5, "outStockDate": "2026-11-02"},
        }
        normalized = MODULE.normalize_query_record(query)
        self.assertEqual(normalized["asin"], "B0REAL1234")
        self.assertEqual(normalized["sku"], "LOCAL-SKU")
        self.assertEqual(normalized["msku"], "MSKU-1")
        self.assertEqual(normalized["purchaseLeadDays"], 36)
        self.assertEqual(normalized["fbaAvailable"], 90)
        self.assertEqual(normalized["sourceAvailable"], 70)
        self.assertEqual(normalized["procurementOpen"], 140)
        self.assertEqual(normalized["agedBuckets"]["over90"], 10)

    def test_product_performance_row_preserves_inventory_layers(self):
        normalized = MODULE.normalize_product_performance_row(
            {
                "asin": "B0REAL1234",
                "sids": [5906],
                "rdate": "2026-10-19",
                "volume": 6,
                "afn_fulfillable_quantity": 95,
                "reserved_customerorders": 3,
                "reserved_fc_transfers": 33,
                "reserved_fc_processing": 2,
                "afn_inbound_receiving_quantity": 4,
                "afn_inbound_shipped_quantity": 1040,
            }
        )
        self.assertEqual(normalized["storeId"], "5906")
        self.assertEqual(normalized["date"], "2026-10-19")
        self.assertEqual(normalized["sales"], 6)
        self.assertEqual(
            normalized["inventoryLayers"],
            {
                "sellable": 95,
                "reservedCustomerOrders": 3,
                "fcTransfers": 33,
                "fcProcessing": 2,
                "receiving": 4,
                "shippedRaw": 1040,
            },
        )

    def test_product_performance_history_keeps_calendar_dates_and_stock_evidence(self):
        rows = [
            {
                "date": "2026-10-18",
                "sales": 2,
                "inventoryLayers": {"sellable": 0, "receiving": 0},
            },
            {
                "date": "2026-10-19",
                "sales": 5,
                "inventoryLayers": {"sellable": 20, "receiving": 0},
            },
        ]

        history = MODULE.product_performance_history(rows, "2026-10-19")

        self.assertEqual(len(history), 60)
        self.assertEqual(history[-2], {
            "date": "2026-10-18", "sales": 2, "fbaSellable": 0, "inboundReceiving": 0
        })
        self.assertEqual(history[-1], {
            "date": "2026-10-19", "sales": 5, "fbaSellable": 20, "inboundReceiving": 0
        })
        self.assertIsNone(history[0]["fbaSellable"])

    def test_history_serialization_supports_numeric_and_enriched_days(self):
        serialized = MODULE.serialize_history(
            [
                1.23456,
                {
                    "date": "2026-10-19",
                    "sales": 5.67891,
                    "fbaSellable": 20,
                    "inboundReceiving": 0,
                },
            ]
        )

        self.assertEqual(serialized[0], 1.2346)
        self.assertEqual(serialized[1]["sales"], 5.6789)
        self.assertEqual(serialized[1]["date"], "2026-10-19")

    def test_shipment_rows_exclude_plans_and_receiving_to_prevent_double_counting(self):
        rows = [
            {
                "货件单号": "FBA-ACTIVE",
                "店铺": "济桓-UK",
                "货件状态": "IN_TRANSIT",
                "送达时段(开始时间)": "2026-11-01",
                "送达时段(结束时间)": "2026-11-08",
                "ASIN": "B0REAL1234",
                "SKU": "SKU-1",
                "申报量": 100,
                "已发货": 90,
                "签收量": 10,
            },
            {
                "货件单号": "FBA-PLAN",
                "店铺": "济桓-UK",
                "货件状态": "READY_TO_SHIP",
                "送达时段(开始时间)": "2026-11-01",
                "送达时段(结束时间)": "2026-11-08",
                "ASIN": "B0REAL1234",
                "SKU": "SKU-1",
                "申报量": 200,
                "已发货": 0,
                "签收量": 0,
            },
            {
                "货件单号": "FBA-RECEIVING",
                "店铺": "济桓-UK",
                "货件状态": "RECEIVING",
                "送达时段(开始时间)": "2026-10-21",
                "送达时段(结束时间)": "2026-10-25",
                "ASIN": "B0REAL1234",
                "SKU": "SKU-1",
                "申报量": 50,
                "已发货": 50,
                "签收量": 20,
            },
        ]

        inbound, _, metadata = MODULE.shipments_from_rows(rows, "2026-10-20", "fixture.xlsx")
        events = inbound[("济桓-UK", "B0REAL1234")]

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["qty"], 80)
        self.assertEqual(events[0]["etaStart"], "2026-11-01")
        self.assertEqual(events[0]["etaEnd"], "2026-11-08")
        self.assertEqual(metadata["plannedRows"], 1)
        self.assertEqual(metadata["receivingRows"], 1)

    def test_zero_shipped_transit_rows_never_become_confirmed_supply(self):
        rows = [
            {
                "货件单号": "FBA-ZERO",
                "店铺": "济桓-UK",
                "货件状态": "IN_TRANSIT",
                "送达时段(开始时间)": "2026-11-01",
                "送达时段(结束时间)": "2026-11-08",
                "ASIN": "B0ZERO1234",
                "SKU": "SKU-Z",
                "申报量": 700,
                "已发货": 0,
                "签收量": 0,
            }
        ]

        inbound, _, metadata = MODULE.shipments_from_rows(rows, "2026-10-20", "fixture.xlsx")
        event = inbound[("济桓-UK", "B0ZERO1234")][0]

        self.assertEqual(event["qty"], 700)
        self.assertFalse(event["confirmed"])
        self.assertFalse(event["quantityVerified"])
        self.assertEqual(metadata["unverifiedRows"], 1)
        self.assertIn("已发货为0", metadata["reminder"])

    def test_missing_eta_workbook_returns_explicit_metadata_without_aborting(self):
        inbound, medians, metadata = MODULE.load_shipments(
            Path("Z:/definitely-missing/FBA货件.xlsx"), "2026-10-20"
        )

        self.assertEqual(dict(inbound), {})
        self.assertEqual(medians, {})
        self.assertEqual(metadata["status"], "missing")
        self.assertIn("补充", metadata["reminder"])


    def test_shared_sku_stock_is_allocated_by_30_day_units(self):
        records = [
            {"listingStatus": 1, "skus": ["SKU-A"], "units30": 30,
             "inventoryLayers": {"local": 100, "overseas": 20, "procurementOpen": 0}, "sourceAvailable": 120},
            {"listingStatus": 1, "skus": ["SKU-A"], "units30": 10,
             "inventoryLayers": {"local": 100, "overseas": 20, "procurementOpen": 0}, "sourceAvailable": 120},
        ]

        changed = MODULE.allocate_shared_sku_stock(records)

        self.assertEqual(changed, 2)
        self.assertAlmostEqual(records[0]["inventoryLayers"]["local"], 75)
        self.assertAlmostEqual(records[1]["inventoryLayers"]["local"], 25)
        self.assertAlmostEqual(records[0]["sourceAvailable"], 90)
        self.assertAlmostEqual(records[0]["stockAllocation"]["share"], 0.75)


if __name__ == "__main__":
    unittest.main()
