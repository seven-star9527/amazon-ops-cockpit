import importlib.util
import sys
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "lingxing_inventory_probe.py"
SPEC = importlib.util.spec_from_file_location("lingxing_inventory_probe", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class LingxingInventoryProbeTests(unittest.TestCase):
    def test_scrub_removes_nested_credentials(self):
        source = {"Authorization": "secret", "nested": [{"token": "secret"}], "asin": "B0TEST1234"}
        self.assertEqual(MODULE.scrub(source)["Authorization"], "[REDACTED]")
        self.assertEqual(MODULE.scrub(source)["nested"][0]["token"], "[REDACTED]")
        self.assertEqual(MODULE.scrub(source)["asin"], "B0TEST1234")

    def test_sample_requests_are_read_only_and_cover_required_sources(self):
        requests = MODULE.build_sample_requests("2026-10-15")
        self.assertEqual(
            set(requests),
            {
                "erp_listing",
                "get_fba_stock_list",
                "query_fba_valid_list",
                "settings_message_inventory_list",
                "platform_v2_page_list",
                "query_product_performance_asin_lists",
                "analytics_show_product_list",
            },
        )
        self.assertEqual(requests["settings_message_inventory_list"]["endTime"], "2026-10-15")
        self.assertEqual(requests["platform_v2_page_list"]["dateUnit"], "4")
        self.assertEqual(requests["platform_v2_page_list"]["dataType"], "1")

    def test_account_requests_request_full_read_only_pages(self):
        requests = MODULE.build_account_requests("2026-10-15")
        self.assertEqual(requests["erp_listing"]["length"], 500)
        self.assertEqual(requests["get_fba_stock_list"]["length"], 500)
        self.assertEqual(requests["query_fba_valid_list"]["restockStatus"], [0, 1])
        self.assertEqual(requests["settings_message_inventory_list"]["size"], 200)
        self.assertEqual(requests["platform_v2_page_list"]["pageSize"], 200)
        self.assertEqual(requests["query_product_performance_asin_lists"]["length"], 10000)
        self.assertEqual(requests["query_product_performance_asin_lists"]["date_view_type"], "day")

    def test_product_performance_response_is_compacted_before_persistence(self):
        response = {
            "data": {
                "data": {
                    "total": 1,
                    "list": [
                        {
                            "asin": "B0TEST1234",
                            "sids": [5906],
                            "rdate": "2026-10-15",
                            "volume": 3,
                            "afn_fulfillable_quantity": 90,
                            "reserved_customerorders": 2,
                            "reserved_fc_transfers": 4,
                            "reserved_fc_processing": 1,
                            "afn_inbound_receiving_quantity": 5,
                            "afn_inbound_shipped_quantity": 100,
                            "huge_unused_field": "do not persist",
                        }
                    ],
                }
            }
        }

        compacted = MODULE.compact_product_performance_response(response)
        row = compacted["data"]["data"]["list"][0]

        self.assertNotIn("huge_unused_field", row)
        self.assertEqual(row["asin"], "B0TEST1234")
        self.assertEqual(row["afn_inbound_shipped_quantity"], 100)


if __name__ == "__main__":
    unittest.main()
