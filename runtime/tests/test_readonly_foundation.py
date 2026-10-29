import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import pytest
from b_ops.collect.cache import CachedSif
from b_ops.collect.replay import ResumeSif
from b_ops.collect.sif import SifError


class Client:
    def __init__(self):
        self.calls = []
        self.fail = False

    def call(self, tool, params):
        self.calls.append((tool, params))
        if self.fail:
            raise SifError('timeout')
        return {'top_keywords': [{'keyword': 'test'}]}


def test_cache_survives_restart_and_scopes(tmp_path):
    live = Client()
    path = tmp_path / 'cache.db'
    for _ in range(3):
        CachedSif(path, live, scope='alice').call('market_get_asin_keyword_signals', {'asin':'A','topN':50})
    assert len(live.calls) == 1
    assert live.calls[0][1]['pageSize'] == 50
    CachedSif(path, live, scope='bob').call('market_get_asin_keyword_signals', {'asin':'A','topN':50})
    assert len(live.calls) == 2


def test_failure_resume_keeps_success_and_cools_down(tmp_path):
    live = Client()
    now = [1000.]
    cache = CachedSif(tmp_path/'cache.db', live, scope='a', clock=lambda: now[0])
    cache.call('market_get_keyword_history', {'keywords':['a']})
    live.fail = True
    with pytest.raises(SifError): cache.call('market_get_keyword_history', {'keywords':['b']})
    with pytest.raises(SifError): cache.call('market_get_keyword_history', {'keywords':['b']})
    assert len(live.calls) == 2
    live.fail = False
    now[0] += 61
    cache.call('market_get_keyword_history', {'keywords':['a']})
    cache.call('market_get_keyword_history', {'keywords':['b']})
    assert len(live.calls) == 3


def test_parallel_requests_fetch_once(tmp_path):
    live = Client()
    clients = [CachedSif(tmp_path/'cache.db', live, scope='a') for _ in range(2)]
    with ThreadPoolExecutor(2) as pool:
        list(pool.map(lambda c: c.call('market_get_keyword_history', {'keywords':['b','a']}), clients))
    assert len(live.calls) == 1


def test_rolling_window_expires_and_write_denied(tmp_path):
    live = Client()
    now = [100000.]
    cache = CachedSif(tmp_path/'cache.db', live, scope='a', clock=lambda: now[0])
    cache.call('market_get_asin_keyword_signals', {'asin':'a'})
    now[0] += 86400
    cache.call('market_get_asin_keyword_signals', {'asin':'a'})
    assert len(live.calls) == 2
    with pytest.raises(ValueError): cache.call('ads_update_bid', {})


def test_resume_does_not_consume_success(tmp_path):
    raw = tmp_path/'raw'/'sif'
    raw.mkdir(parents=True)
    (raw/'a.json').write_text(json.dumps({'tool':'market_get_asin_keyword_signals','params':{'topN':50},'response':{'ok':1}}))
    live = Client()
    client = ResumeSif(tmp_path, live)
    assert client.call('market_get_asin_keyword_signals', {'pageSize':50}) == {'ok':1}
    assert client.call('market_get_asin_keyword_signals', {'pageSize':50}) == {'ok':1}
    assert not live.calls


def test_single_writer_blocks_and_recovers(tmp_path):
    from b_ops.run_lock import single_writer
    with single_writer(tmp_path):
        with pytest.raises((RuntimeError, OSError)):
            with single_writer(tmp_path): pass
    with single_writer(tmp_path): pass


def test_data_root_is_external(monkeypatch, tmp_path):
    from b_ops.paths import data_root
    assert data_root(tmp_path) == tmp_path.resolve()
    with pytest.raises(ValueError): data_root(Path(__file__).resolve().parents[2])


def test_sparse_history_preserves_unknown():
    import importlib.util
    path = Path(__file__).resolve().parents[1] / 'pmc/scripts/build_real_snapshot.py'
    spec = importlib.util.spec_from_file_location('snapshot_foundation', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    days = module.product_performance_history([{'date':'2026-10-29','sales':4}], '2026-10-29')
    assert days[-1]['sales'] == 4
    assert days[-2]['sales'] is None
    assert days[-1]['fbaSellable'] is None
    assert module.serialize_history(days)[-2]['sales'] is None
