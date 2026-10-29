import json

from b_ops.collect.replay import ReplayLingxing, ReplayMissing, ReplaySif, ResumeSif, ExtendSif
from b_ops.collect.refresh import RecordedSif


def test_replay_matches_only_exact_recorded_tool_and_parameters(tmp_path):
    raw = tmp_path/'raw'/'lingxing'
    raw.mkdir(parents=True)
    (raw/'x.json').write_text(json.dumps({'tool':'erp_listing','params':{'offset':0},'response':{'code':1,'data':{'list':[]}}}),encoding='utf-8')
    client = ReplayLingxing(tmp_path)
    assert client.read('erp_listing',{'offset':0})['code'] == 1
    try:
        client.read('erp_listing',{'offset':0})
    except ReplayMissing:
        pass
    else:
        assert False, 'replay may not invent a second response'


def test_sif_replay_keeps_same_params_and_fails_closed(tmp_path):
    raw=tmp_path/'raw'/'sif';raw.mkdir(parents=True)
    (raw/'x.json').write_text(json.dumps({'tool':'market_get_keyword_history','params':{'keywords':['one']},
                                          'response':{'keywords':[{'keyword':'one'}]}}),encoding='utf-8')
    client=ReplaySif(tmp_path)
    assert client.call('market_get_keyword_history',{'keywords':['one']})['keywords'][0]['keyword']=='one'
    try:client.call('market_get_keyword_history',{'keywords':['two']})
    except ReplayMissing:pass
    else:assert False,'different keyword list must never reuse a response'


def test_sif_resume_reuses_exact_partial_raw_then_fetches_missing_live(tmp_path):
    raw=tmp_path/'raw'/'sif';raw.mkdir(parents=True)
    (raw/'x.json').write_text(json.dumps({'tool':'market_get_keyword_history',
        'params':{'keywords':['one']},'response':{'keywords':[{'keyword':'one'}]}}),encoding='utf-8')
    class Live:
        def __init__(self):self.calls=[]
        def call(self,tool,params):
            self.calls.append((tool,params))
            return {'keywords':[{'keyword':params['keywords'][0]}]}
    live=Live()
    client=ResumeSif(tmp_path,live)
    assert client.call('market_get_keyword_history',{'keywords':['one']})['keywords'][0]['keyword']=='one'
    assert client.call('market_get_keyword_history',{'keywords':['two']})['keywords'][0]['keyword']=='two'
    assert client.replayed_calls==1 and client.live_calls==1
    assert live.calls==[('market_get_keyword_history',{'keywords':['two']})]
    target=tmp_path/'new-run';target.mkdir()
    recorded=[]
    restarted=RecordedSif(ResumeSif(tmp_path,live),target,'b-new',recorded)
    restarted.call('market_get_keyword_history',{'keywords':['one']})
    restarted.call('market_get_keyword_history',{'keywords':['three']})
    assert recorded[0]['replayed_from_b_run']==tmp_path.name
    assert 'replayed_from_b_run' not in recorded[1]


def test_completed_same_day_b_source_can_extend_only_exact_verified_sif_calls(tmp_path):
    import hashlib
    source = tmp_path / 'b-20261014-090000-abcdef'
    raw = source / 'raw' / 'sif'
    raw.mkdir(parents=True)
    doc = {'run_id': source.name, 'provider': 'sif', 'tool': 'market_get_keyword_history',
           'params': {'keywords': ['one']}, 'response': {'keywords': [{'keyword': 'one'}]}}
    data = json.dumps(doc).encode('utf-8')
    (raw / 'x.json').write_bytes(data)
    manifest = {'run_id': source.name, 'state': 'complete', 'source_calls': [
        {'provider': 'sif', 'tool': doc['tool'], 'params': doc['params'],
         'file': 'raw/sif/x.json', 'sha256': hashlib.sha256(data).hexdigest()}]}
    (source / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')

    class Live:
        def __init__(self): self.calls = []
        def call(self, tool, params):
            self.calls.append((tool, params))
            return {'keywords': [{'keyword': params['keywords'][0]}]}

    live = Live()
    client = ExtendSif(source, live)
    assert client.call(doc['tool'], doc['params']) == doc['response']
    assert client.call(doc['tool'], {'keywords': ['two']})['keywords'][0]['keyword'] == 'two'
    assert client.replayed_calls == 1 and client.live_calls == 1
    assert live.calls == [(doc['tool'], {'keywords': ['two']})]
    (raw / 'x.json').write_bytes(data + b' ')
    try:
        ExtendSif(source, Live())
    except ValueError as exc:
        assert 'hash' in str(exc)
    else:
        assert False, 'tampered completed source must be rejected'
