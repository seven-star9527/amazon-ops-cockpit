import unittest

from pmc.scripts.fuse_board import fuse_board


class FuseBoardTests(unittest.TestCase):
    def test_store_and_asin_join_is_exact_and_old_inventory_issue_replaced(self):
        base = {"run_id":"b-old", "as_of_date":"2026-10-14", "products":{
            "1|UK|B000000001":{"key":"1|UK|B000000001","sid":"1","site":"UK","asin":"B000000001",
                "status":"1","shop":"店铺","issues":[{"domain":"inventory","title":"旧断货"},
                    {"domain":"advertising","title":"广告保留"}]},
            "2|UK|B000000001":{"key":"2|UK|B000000001","sid":"2","site":"UK","asin":"B000000001",
                "status":"1","shop":"店铺2","issues":[]},
        },"coverage":{}}
        row = {"storeId":"1","asin":"B000000001","store":"店铺","title":"测试品","asOf":"2026-10-21",
               "listingStatus":1,"risk":"critical","primaryIssue":{"label":"断货"},
               "forecast":{"effectiveDays":60},"timeline":{"stockoutDate":"2026-11-01"}}
        result = fuse_board(base,{"metadata":{"asOf":"2026-10-21"},"records":[row]})
        self.assertEqual(result["products"]["1|UK|B000000001"]["inventory_pmc"]["storeId"],"1")
        self.assertNotIn("inventory_pmc",result["products"]["2|UK|B000000001"])
        self.assertEqual([i["domain"] for i in result["products"]["1|UK|B000000001"]["issues"]],
                         ["inventory","advertising"])
        self.assertEqual(result["as_of_date"],"2026-10-14")
        self.assertEqual(result["inventory_batch"]["as_of"],"2026-10-21")
