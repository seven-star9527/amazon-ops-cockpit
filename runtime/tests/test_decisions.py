import pytest

from b_ops.model.storage import StateStore


def test_decision_is_append_only_and_optimistic_versioned(tmp_path):
    state = StateStore(tmp_path / 'state.sqlite3')
    first = state.save_decision('b-r1', 'action-a', 'p1', 'accept', '确认', expected_version=0)
    assert first['version'] == 1
    with pytest.raises(ValueError, match='version'):
        state.save_decision('b-r1', 'action-a', 'p1', 'reject', '冲突', expected_version=0)
    second = state.save_decision('b-r1', 'action-a', 'p1', 'reject', '更改意见', expected_version=1)
    assert second['version'] == 2
    assert state.latest_decisions('b-r1')['action-a']['value'] == 'reject'
    assert len(state.decision_history('b-r1')) == 2


def test_invalid_decision_state_is_rejected(tmp_path):
    state = StateStore(tmp_path / 'state.sqlite3')
    with pytest.raises(ValueError):
        state.save_decision('b-r1','a','p','execute','',expected_version=0)


def test_exact_bid_is_preserved_in_review_history(tmp_path):
    state = StateStore(tmp_path / 'state.sqlite3')
    saved = state.save_decision('b-r1','a','p','accept','',expected_version=0,bid=0.72)
    assert saved['bid'] == 0.72
    assert state.latest_decisions('b-r1')['a']['bid'] == 0.72
