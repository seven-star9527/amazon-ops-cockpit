from b_ops.collect.sif_discovery import competitor_asin, discover_competitors, competitor_gap_terms, collect_competitor_pool
from b_ops.collect import sif_discovery as discovery
from b_ops.model.storage import StateStore


class FakeSif:
    def __init__(self):
        self.calls = []

    def call(self, tool, args):
        self.calls.append((tool, args))
        if tool == "market_discover_competitors":
            return {"competitors": [
                {"asin": "[B0CHXTHK7N](https://www.amazon.co.uk/dp/B0CHXTHK7N)", "monthly_orders": 230},
                {"asin": "B0AA111111", "monthly_orders": 110},
                {"asin": "B0AA222222", "monthly_orders": 90},
                {"asin": "B0AA333333", "monthly_orders": 80},
            ]}
        if tool == "market_get_asin_profile":
            return {"list": [
                {"asin": "B0FGTVP62B", "title": "Toddler Kids Knife Set", "price": 20,
                 "bsr_list": [{"category_name": "Toys & Games"}]},
                *[{"asin": asin, "title": "Kids Knife Set for Toddlers", "price": 19,
                   "bsr_list": [{"category_name": "Toys & Games"}]}
                  for asin in ("B0CHXTHK7N", "B0AA111111", "B0AA222222")],
            ]}
        return {"top_keywords": [{"keyword": "kids knife set"}, {"keyword": "own word"}]}


def test_competitor_identity_and_bounded_discovery():
    assert competitor_asin("[B0CHXTHK7N](https://www.amazon.co.uk/dp/B0CHXTHK7N)") == "B0CHXTHK7N"
    client = FakeSif()
    rows = discover_competitors(client, site="UK", asin="B0FGTVP62B", seed="kids chopping kit", limit=3)
    assert [r["asin"] for r in rows] == ["B0CHXTHK7N", "B0AA111111", "B0AA222222"]
    assert all(r["source"] == "sif_serp_discovery" for r in rows)
    assert client.calls[0][1]["max_results"] == 3


def test_competitor_seed_prefers_product_intent_over_high_share_generic_word():
    words = [{"keyword": "knife set", "traffic_share": 0.80},
             {"keyword": "toddler knife set for chopping", "traffic_share": 0.068},
             {"keyword": "kids camera", "traffic_share": 0.05}]
    assert discovery.choose_competitor_seed(words,
        "Yeeammk Toddler Knife Set with Cooking Tools for Kids") == "toddler knife set for chopping"
    tablet = [{"keyword": "kids tablet", "traffic_share": 0.73},
              {"keyword": "baby tablet", "traffic_share": 0.0046}]
    assert discovery.choose_competitor_seed(tablet,
        "Yeeammk Baby Learning Tablet with Easy-Grip Handles") == "baby tablet"
    dense = [{"keyword": "toddler montessori kitchen tools with storage", "traffic_share": .12},
             {"keyword": "kids knife set for chopping", "traffic_share": .08}]
    assert discovery.choose_competitor_seed(dense,
        "Yeeammk Toddler Knife Set with Montessori Cooking Tools for Kids") == "kids knife set for chopping"


def test_older_b00_asin_is_not_dropped_from_sif_candidates():
    assert competitor_asin("[B00SYSRFBC](https://www.amazon.co.uk/dp/B00SYSRFBC)") == "B00SYSRFBC"


def test_profile_gate_keeps_candidates_visible_but_only_queries_relevant_gap(tmp_path):
    class ProfileSif:
        def __init__(self):
            self.calls = []

        def call(self, tool, args):
            self.calls.append((tool, args))
            if tool == "market_discover_competitors":
                return {"competitors": [
                    {"asin": "B0B7J1K3RG", "price": 16.98, "monthly_orders": "600+"},
                    {"asin": "B0BG55YRZW", "price": 16.99, "monthly_orders": "300+"},
                    {"asin": "B0UNKNOWN1", "price": 17.00},
                ]}
            if tool == "market_get_asin_profile":
                return {"list": [
                    {"asin": "B0FGTVP62B", "title": "Toddler Knife Set with Cooking Tools for Kids",
                     "price": 23.79, "bsr_list": [{"category_name": "Toys & Games"}]},
                    {"asin": "B0B7J1K3RG", "title": "Kids Kitchen Knife Set for Cooking",
                     "brand": "Tyrkuiy", "price": 16.98,
                     "bsr_list": [{"category_name": "Toys & Games"}]},
                    {"asin": "B0BG55YRZW", "title": "Kids Camera with Video",
                     "price": 16.99, "bsr_list": [{"category_name": "Toys & Games"}]},
                ]}
            if tool == "market_get_asin_keyword_signals":
                return {"top_keywords": [{"keyword": "kids cooking knives"}]}
            raise AssertionError(tool)

    client = ProfileSif()
    state = StateStore(tmp_path / "state.sqlite3")
    result = collect_competitor_pool(client, state, sid="s1", site="UK",
                                     parent_asin="B0FR4645V5", asin="B0FGTVP62B",
                                     seed="toddler knife set for chopping", run_id="r2",
                                     own_terms=set(), target_title="Toddler Knife Set with Cooking Tools for Kids",
                                     target_price=23.79)
    assert [row["asin"] for row in result["competitors"]] == ["B0B7J1K3RG"]
    assert result["candidate_terms"] == 1
    assert {row["asin"]: row["relevance_state"] for row in result["candidates"]} == {
        "B0B7J1K3RG": "plausible", "B0BG55YRZW": "intent_mismatch",
        "B0UNKNOWN1": "profile_missing"}
    assert [args["asin"] for tool, args in client.calls if tool == "market_get_asin_keyword_signals"] == ["B0B7J1K3RG"]
    assert sum(tool == "market_get_asin_profile" for tool, _ in client.calls) == 1
    assert state.list_competitors("s1", "UK", "B0FR4645V5")[0]["asin"] == "B0B7J1K3RG"


def test_category_mismatch_never_becomes_competitor_gap(tmp_path):
    class ProfileSif:
        def call(self, tool, args):
            if tool == "market_discover_competitors":
                return {"competitors": [{"asin": "B09WYZ4CNS", "price": 179.99}]}
            if tool == "market_get_asin_profile":
                return {"list": [
                    {"asin": "B0FGTVP62B", "title": "Toddler Knife Set", "price": 23.79,
                     "bsr_list": [{"category_name": "Toys & Games"}]},
                    {"asin": "B09WYZ4CNS", "title": "Adult Kitchen Knife Set", "price": 179.99,
                     "bsr_list": [{"category_name": "Home & Kitchen"}]},
                ]}
            raise AssertionError("irrelevant competitor must not fetch gap terms")

    state = StateStore(tmp_path / "state.sqlite3")
    result = collect_competitor_pool(ProfileSif(), state, sid="s1", site="UK",
                                     parent_asin="B0FR4645V5", asin="B0FGTVP62B",
                                     seed="knife set", run_id="r1", own_terms=set(),
                                     target_title="Toddler Knife Set", target_price=23.79)
    assert result["competitors"] == []
    assert result["candidates"][0]["relevance_state"] == "category_mismatch"
    assert result["candidate_keywords"] == []


def test_root_fallback_recovers_relevant_toy_tablet_without_android_tablets(tmp_path):
    class RootSif:
        def __init__(self): self.calls=[]
        def call(self, tool, args):
            self.calls.append((tool,args))
            if tool == "market_discover_competitors":
                return {"competitors":[{"asin":"B0DP9CL8X9","price":39}]}
            if tool == "market_get_keyword_root_competitors":
                return {"competitors":[{"asin":"[B0FJRLVC3K](https://www.amazon.co.uk/dp/B0FJRLVC3K)"},
                                       {"asin":"B0BL5QHW4M"}]}
            if tool == "market_get_asin_profile":
                profiles={
                  "B0H9KDMFC4":("Baby Learning Tablet Toy",16.99,"Toys & Games"),
                  "B0DP9CL8X9":("Kids Tablet Android WiFi",39,"Computers & Accessories"),
                  "B0FJRLVC3K":("Multilingual Baby Learning Tablet Toy",22.14,"Toys & Games"),
                  "B0BL5QHW4M":("Fire HD Kids tablet",114.99,"Computers & Accessories")}
                return {"list":[{"asin":asin,"title":profiles[asin][0],"price":profiles[asin][1],
                    "bsr_list":[{"category_name":profiles[asin][2]}]}
                    for asin in args["asins"]]}
            if tool == "market_get_asin_keyword_signals":
                assert args["asin"]=="B0FJRLVC3K"
                return {"top_keywords":[{"keyword":"baby music tablet"}]}
            raise AssertionError(tool)
    client=RootSif()
    result=collect_competitor_pool(client,StateStore(tmp_path/'state.sqlite3'),sid='s1',site='UK',
        parent_asin='B0HMHB4Z26',asin='B0H9KDMFC4',seed='baby tablet',run_id='r1',own_terms=set(),
        target_title='Baby Learning Tablet Toy',target_price=16.99)
    assert [row['asin'] for row in result['competitors']]==['B0FJRLVC3K']
    assert result['root_state']=='verified'
    assert result['candidate_keywords']==['baby music tablet']
    assert sum(tool=='market_get_keyword_root_competitors' for tool,_ in client.calls)==1


def test_competitor_gap_terms_do_not_claim_exact_target():
    client = FakeSif()
    result = competitor_gap_terms(client, site="UK", competitor="B0CHXTHK7N",
                                  own_terms={"own word"}, max_terms=10)
    assert [row["keyword"] for row in result] == ["kids knife set"]
    assert result[0]["source"] == "sif_competitor_gap"
    assert result[0]["target_state"] == "unverified"


def test_manual_competitor_pending_until_next_run_and_sif_source_survives(tmp_path):
    state = StateStore(tmp_path / "state.sqlite3")
    state.upsert_discovered_competitors("s1", "UK", "B0PARENT01", ["B0CHXTHK7N"], "r1")
    state.stage_competitor_change("s1", "UK", "B0PARENT01", "B0AA111111", "add", "r1")
    current = state.list_competitors("s1", "UK", "B0PARENT01")
    assert [row["asin"] for row in current if row["active"]] == ["B0CHXTHK7N"]
    assert next(row for row in current if row["asin"] == "B0AA111111")["pending"] == "add"
    state.apply_pending_tracking("r2")
    assert {row["asin"] for row in state.list_competitors("s1", "UK", "B0PARENT01") if row["active"]} == {
        "B0CHXTHK7N", "B0AA111111"}
    products=[{"key":"s1|UK|B0FGTVP62B","sid":"s1","site":"UK","asin":"B0FGTVP62B",
               "parent_asin":"B0PARENT01"}]
    assert state.competitor_priority_keys(products) == {"s1|UK|B0FGTVP62B"}
    state.stage_competitor_change("s1", "UK", "B0PARENT01", "B0CHXTHK7N", "remove", "r2")
    state.apply_pending_tracking("r3")
    assert not next(row for row in state.list_competitors("s1", "UK", "B0PARENT01")
                    if row["asin"] == "B0CHXTHK7N")["active"]


def test_removed_auto_competitor_is_not_rediscovered_or_queried(tmp_path):
    state=StateStore(tmp_path/'state.sqlite3')
    state.upsert_discovered_competitors('s1','UK','B0PARENT01',['B0CHXTHK7N'],'r1')
    state.stage_competitor_change('s1','UK','B0PARENT01','B0CHXTHK7N','remove','r1')
    state.apply_pending_tracking('r2')
    class Again(FakeSif):
        def call(self,tool,args):
            if tool=='market_get_keyword_root_competitors':return {'competitors':[]}
            return super().call(tool,args)
    client=Again()
    result=collect_competitor_pool(client,state,sid='s1',site='UK',parent_asin='B0PARENT01',
        asin='B0FGTVP62B',seed='kids knife set for chopping',run_id='r2',own_terms=set(),
        max_competitors=1,target_title='Toddler Kids Knife Set',target_price=20)
    assert all(item['asin']!='B0CHXTHK7N' for item in result['competitors'])
    assert all(args.get('asin')!='B0CHXTHK7N' for tool,args in client.calls
               if tool=='market_get_asin_keyword_signals')


def test_pool_merges_external_gap_with_existing_word_without_auto_tracking(tmp_path):
    state = StateStore(tmp_path / "state.sqlite3")
    state.add_keyword("UK", "B0FGTVP62B", "kids knife set", "lingxing_search_term", "internal", "r1", "s1")
    result = collect_competitor_pool(FakeSif(), state, sid="s1", site="UK", parent_asin="B0PARENT01",
                                     asin="B0FGTVP62B", seed="kids chopping kit", run_id="r2",
                                     own_terms={"own word"}, max_competitors=1)
    assert result["state"] == "verified"
    assert result["competitors"][0]["asin"] == "B0CHXTHK7N"
    words = state.list_keywords("UK", "B0FGTVP62B", sid="s1")
    assert len(words) == 1
    assert words[0]["sources"] == ["lingxing_search_term", "sif_competitor_gap"]
    assert words[0]["tracking"]["state"] == "candidate"


def test_manual_competitor_still_queries_when_auto_discovery_fails(tmp_path):
    state = StateStore(tmp_path / "state.sqlite3")
    state.stage_competitor_change("s1", "UK", "B0PARENT01", "B0CHXTHK7N", "add", "r1")
    state.apply_pending_tracking("r2")

    class DiscoveryFails(FakeSif):
        def call(self, tool, args):
            if tool == "market_discover_competitors":
                raise RuntimeError("discovery unavailable")
            return super().call(tool, args)

    result = collect_competitor_pool(DiscoveryFails(), state, sid="s1", site="UK",
                                     parent_asin="B0PARENT01", asin="B0FGTVP62B",
                                     seed="kids chopping kit", run_id="r3", own_terms=set())
    assert result["state"] == "partial"
    assert result["discovery_state"] == "source_failed"
    assert result["competitors"][0]["asin"] == "B0CHXTHK7N"
    assert result["competitors"][0]["state"] == "verified"
    assert result["candidate_terms"] == 2
    no_seed = collect_competitor_pool(DiscoveryFails(), state, sid="s1", site="UK",
                                      parent_asin="B0PARENT01", asin="B0FGTVP62B",
                                      seed="", run_id="r4", own_terms=set())
    assert no_seed["discovery_state"] == "no_seed"
    assert no_seed["competitors"][0]["state"] == "verified"
