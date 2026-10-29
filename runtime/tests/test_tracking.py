from b_ops.model.storage import StateStore


def test_sif_core_is_store_specific_and_manual_removal_waits_for_next_run(tmp_path):
    state = StateStore(tmp_path / "state.sqlite3")
    word_id = state.add_keyword("US", "B012345678", "kids scissors", "sif_asin_signals", "SIF", "r1", "s1")
    state.add_keyword("US", "B012345678", "kids scissors", "sif_asin_signals", "SIF", "r1", "s2")
    state.mark_sif_core(word_id, "s1", "r1")
    state.mark_sif_core(word_id, "s2", "r1")
    state.stage_tracking_change("s1", "US", "B012345678", "kids scissors", "remove", "r1")
    assert state.tracking_state(word_id, "s1")["state"] == "active"
    assert state.tracking_state(word_id, "s1")["pending"] == "remove"
    state.apply_pending_tracking("r2")
    state.mark_sif_core(word_id, "s1", "r2")
    assert state.tracking_state(word_id, "s1")["state"] == "suppressed"
    assert state.tracking_state(word_id, "s2")["state"] == "active"
    state.stage_tracking_change("s1", "US", "B012345678", "kids scissors", "add", "r2")
    state.apply_pending_tracking("r3")
    assert state.tracking_state(word_id, "s1")["state"] == "active"


def test_new_manual_word_is_pending_then_active_and_priority_is_next_run(tmp_path):
    state = StateStore(tmp_path / "state.sqlite3")
    word_id = state.stage_tracking_change("s1", "US", "B012345678", "manual word", "add", "r1")
    assert state.tracking_state(word_id, "s1")["state"] == "candidate"
    assert state.tracking_state(word_id, "s1")["pending"] == "add"
    state.stage_sif_priority("s1", "US", "B012345678", True, "r1")
    assert state.sif_priority_keys() == set()
    state.apply_pending_tracking("r2")
    assert state.tracking_state(word_id, "s1")["state"] == "active"
    assert state.sif_priority_keys() == {"s1|US|B012345678"}


def test_tracking_events_preserve_history_and_cancel_pending(tmp_path):
    state = StateStore(tmp_path / "state.sqlite3")
    word_id = state.add_keyword("US", "B012345678", "kids scissors", "sif_asin_signals", "SIF", "r1", "s1")
    state.mark_sif_core(word_id, "s1", "r1")
    version = state.tracking_version()
    state.stage_tracking_change("s1", "US", "B012345678", "kids scissors", "remove", "r1")
    assert state.tracking_version() == version + 1
    state.cancel_tracking_change("s1", word_id, "r1")
    assert state.tracking_state(word_id, "s1")["pending"] is None
    assert state.tracking_state(word_id, "s1")["state"] == "active"


def test_keyword_list_for_store_excludes_other_store_membership(tmp_path):
    state = StateStore(tmp_path / "state.sqlite3")
    state.add_keyword("US", "B012345678", "store one word", "sif_asin_signals", "SIF", "r1", "s1")
    state.add_keyword("US", "B012345678", "store two word", "sif_asin_signals", "SIF", "r1", "s2")
    assert [row["keyword"] for row in state.list_keywords("US", "B012345678", sid="s1")] == ["store one word"]
    assert [row["keyword"] for row in state.list_keywords("US", "B012345678", sid="s2")] == ["store two word"]


def test_batch_tracking_is_deduplicated_atomic_and_next_run_only(tmp_path):
    state = StateStore(tmp_path / "state.sqlite3")
    keys = state.stage_tracking_batch("s1", "US", "B012345678",
                                      ["Kids Scissors", "kids  scissors", "toddler knife"], "add", "r1")
    assert len(keys) == 2
    assert state.tracking_version() == 2
    assert {r["tracking"]["pending"] for r in state.list_keywords("US", "B012345678", sid="s1")} == {"add"}
    before = state.tracking_version()
    import pytest
    with pytest.raises(ValueError):
        state.stage_tracking_batch("s1", "US", "B012345678", ["valid term", "B012345678"], "add", "r1")
    assert state.tracking_version() == before
    assert "valid term" not in [r["keyword"] for r in state.list_keywords("US", "B012345678", sid="s1")]
    state.apply_pending_tracking("r2")
    assert {r["tracking"]["state"] for r in state.list_keywords("US", "B012345678", sid="s1")} == {"active"}
