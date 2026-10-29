import json
import tempfile
import unittest
from pathlib import Path

from pmc.scripts.assemble_sources import assemble


class AssembleSourcesTests(unittest.TestCase):
    def fixture(self, root, *, duplicate=False):
        as_of = "2026-10-21"
        for name in ("erp_listing", "get_fba_stock_list", "query_fba_valid_list", "settings_message_inventory_list"):
            rows = {"total": 0, "records": []} if name == "settings_message_inventory_list" else []
            (root / f"{name}.json").write_text(json.dumps({"as_of": as_of, "reported_total": 0, "rows": rows}), encoding="utf-8")
        row = {"asin": "B000000001", "sids": [1], "rdate": as_of, "volume": 1}
        (root / "performance_2026-10-21.json").write_text(json.dumps({"as_of": as_of, "reported_total": 2 if duplicate else 1,
            "rows": [row, row] if duplicate else [row], "params": {"start_date": as_of, "end_date": as_of}}), encoding="utf-8")

    def test_contract_wraps_each_source_and_preserves_date(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.fixture(root)
            result = assemble(root)
            self.assertEqual(result["as_of"], "2026-10-21")
            self.assertEqual(len(result["tools"]["query_product_performance_asin_lists"]["response"]["data"]["data"]["list"]), 1)
            self.assertEqual(result["tools"]["erp_listing"]["response"]["data"]["data"]["list"], [])

    def test_duplicate_daily_identity_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.fixture(root, duplicate=True)
            with self.assertRaises(ValueError):
                assemble(root)

    def test_mixed_as_of_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.fixture(root)
            path = root / "get_fba_stock_list.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            data["as_of"] = "2026-10-20"
            path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(ValueError):
                assemble(root)
