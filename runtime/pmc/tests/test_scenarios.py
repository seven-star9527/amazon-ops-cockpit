import tempfile
import unittest
from pathlib import Path

from pmc.scripts.save_scenario import save_scenario


class ScenarioTests(unittest.TestCase):
    def test_save_updates_only_exact_store_asin_and_preserves_other_entries(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "state.json"
            first = save_scenario(path, {"store":"济桓-UK","asin":"B000000001","name":"旺季",
                "params":{"demandMultiplier":2,"purchaseLeadDays":30}},
                allowed={("济桓-UK","B000000001"),("吉福荣-UK","B000000001")}, make_default=True)
            second = save_scenario(path, {"store":"吉福荣-UK","asin":"B000000001","name":"平稳",
                "params":{"demandMultiplier":1}},
                allowed={("济桓-UK","B000000001"),("吉福荣-UK","B000000001")}, make_default=False)
            self.assertEqual(len(second["scenarios"]),2)
            self.assertTrue(first["scenarios"][0]["isDefault"])
            self.assertFalse(second["scenarios"][1]["isDefault"])

    def test_invalid_range_or_unknown_product_does_not_touch_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "state.json"
            draft={"store":"济桓-UK","asin":"B000000001","name":"超限","params":{"transitDays":-5}}
            with self.assertRaises(ValueError):
                save_scenario(path,draft,allowed={("济桓-UK","B000000001")},make_default=True)
            self.assertFalse(path.exists())
            draft["params"]={"transitDays":50}
            with self.assertRaises(ValueError):
                save_scenario(path,draft,allowed={("吉福荣-UK","B000000001")},make_default=True)
            self.assertFalse(path.exists())
