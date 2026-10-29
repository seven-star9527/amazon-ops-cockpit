from b_ops.model.storage import StateStore
import os


def test_active_keyword_survives_next_run_and_merges_sources(tmp_path):
    store = StateStore(tmp_path / "state.sqlite3")
    first = store.add_keyword("UK", "B012345678", "  Kids   Scissors ", "sif_gap", "竞品覆盖", "r1")
    again = store.add_keyword("UK", "B012345678", "kids scissors", "lingxing_search_term", "有单搜索词", "r2")
    assert first == again
    assert len(store.list_keywords("UK", "B012345678")) == 1
    row = store.list_keywords("UK", "B012345678")[0]
    assert row["status"] == "active"
    assert set(row["sources"]) == {"sif_gap", "lingxing_search_term"}
    assert row["first_run_id"] == "r1"


def test_rank_observations_append_and_missing_day_is_not_previous_rank(tmp_path):
    store = StateStore(tmp_path / "state.sqlite3")
    key = store.add_keyword("UK", "B012345678", "kids scissors", "sif", "相关", "r1")
    store.record_rank(key, "2026-10-10", "natural", 12, "absolute_rank", "r1")
    store.record_rank(key, "2026-10-11", "natural", None, "not_returned", "r2")
    window = store.rank_window(key, "2026-10-10", "2026-10-11")
    assert [item["rank"] for item in window] == [12, None]
    assert [item["state"] for item in window] == ["absolute_rank", "not_returned"]


def test_reported_ad_position_is_saved_as_text_not_invented_absolute_rank(tmp_path):
    store=StateStore(tmp_path/'state.sqlite3')
    key=store.add_keyword('UK','B012345678','kids spray mop','sif','广告位','r1')
    store.record_rank(key,'2026-10-11','advertising',None,'reported_position','r1',display='p2,3/12')
    row=store.rank_window(key,'2026-10-11','2026-10-11')[0]
    assert row['rank'] is None and row['display']=='p2,3/12'
    assert row['state']=='reported_position'


def test_store_membership_is_separate_from_market_rank_identity(tmp_path):
    store = StateStore(tmp_path / "state.sqlite3")
    key = store.add_keyword("UK", "B012345678", "kids scissors", "sif", "相关", "r1", sid="2907")
    same = store.add_keyword("UK", "B012345678", "KIDS SCISSORS", "sif", "相关", "r2", sid="5906")
    assert key == same
    assert store.keyword_memberships(key) == ["2907", "5906"]


def test_sif_success_is_durable_so_uncovered_asins_can_be_selected_next(tmp_path):
    store=StateStore(tmp_path/'state.sqlite3')
    store.record_sif_fetch('UK','B012345678','r1','verified')
    store.record_sif_fetch('UK','B098765432','r1','source_failed')
    success=store.sif_last_success_map()
    assert ('UK','B012345678') in success
    assert ('UK','B098765432') not in success
    store.record_sif_fetch('UK','B098765432','r2','no_rows')
    assert ('UK','B098765432') in store.sif_last_success_map()
    store.add_keyword('UK','B000000001','known sif term','sif_asin_signals','old source','r0')
    assert ('UK','B000000001') in store.sif_last_success_map()


def test_bulk_add_keeps_one_asset_per_word_and_distinct_sources(tmp_path):
    store = StateStore(tmp_path / "state.sqlite3")
    store.add_keywords([
        {"site":"US","asin":"B012345678","keyword":"Kids Scissors","source":"lingxing","reason":"搜索词","run_id":"r1","sid":"1"},
        {"site":"US","asin":"B012345678","keyword":"kids  scissors","source":"sif","reason":"外部词","run_id":"r1","sid":"1"},
    ])
    rows = store.list_keywords("US","B012345678")
    assert len(rows) == 1
    assert rows[0]["sources"] == ["lingxing","sif"]


def test_state_file_closes_before_atomic_publish(tmp_path):
    path = tmp_path / "staged.sqlite3"
    store = StateStore(path)
    store.add_keyword("US","B012345678","kids scissors","sif","rank","r1")
    store.list_keywords("US","B012345678")
    os.replace(path, tmp_path / "published.sqlite3")
