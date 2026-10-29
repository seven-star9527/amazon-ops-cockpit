import asyncio
import hashlib
import json

from httpx import ASGITransport, AsyncClient

from b_ops.diagnose.sif_probe import build_probe_candidates
from b_ops.render import render_board
from b_ops.server import create_app


def _board():
    product = {
        'key': 's1|UK|B012345678', 'sid': 's1', 'site': 'UK', 'asin': 'B012345678',
        'status': '1', 'name': '儿童剪刀', 'weeks': [], 'issues': [], 'actions': [],
        'keyword_state': {'sif_state': 'verified', 'terms': [
            {'id': 'sif-only', 'keyword': 'toddler scissors', 'normalized': 'toddler scissors',
             'sources': ['sif_asin_signals'], 'weekly_volume': 500,
             'tracking': {'state': 'active'}, 'internal_evidence': None},
            {'id': 'has-data', 'keyword': 'kids scissors', 'normalized': 'kids scissors',
             'sources': ['sif_asin_signals', 'lingxing_search_term'],
             'tracking': {'state': 'active'}, 'internal_evidence': {'orders': 3}},
            {'id': 'asin-target', 'keyword': 'B0FGTVP62B', 'sources': ['sif_asin_signals'],
             'tracking': {'state': 'active'}},
        ]}}
    return {'run_id': 'b-probe', 'products': {product['key']: product}, 'actions': [],
            'profile_to_sid': {'p1': 's1'}, 'coverage': {},
            'status': {'ads_diagnosis': {'source_complete': True}}}


def test_sif_external_term_is_an_intent_candidate_not_an_executable_exact_action():
    probes = build_probe_candidates(_board())
    assert list(probes) == ['sif-probe:p1:sif-only']
    probe = probes['sif-probe:p1:sif-only']
    assert probe['kind'] == 'sif_probe'
    assert probe['reviewable'] is False and probe['executable'] is False
    assert probe['weekly_volume'] == 500
    assert 'not_targeted' not in probe
    incomplete = _board()
    incomplete['status']['ads_diagnosis']['source_complete'] = False
    assert build_probe_candidates(incomplete) == {}
    stale = _board()
    stale['products']['s1|UK|B012345678']['keyword_state']['sif_state'] = 'source_failed'
    assert build_probe_candidates(stale) == {}


def test_competitor_gap_can_request_validation_but_active_exact_cannot_duplicate():
    board = _board()
    terms = board['products']['s1|UK|B012345678']['keyword_state']['terms']
    terms.append({'id':'gap','keyword':'kids chopping kit','normalized':'kids chopping kit',
                  'sources':['sif_competitor_gap'],'current_competitor_gap':True,'weekly_volume':None,
                  'tracking':{'state':'candidate'},'internal_evidence':None,
                  'keyword_targets':[]})
    terms[0]['keyword_targets'] = [{'target_id':'t1','match_type':'exact',
                                   'target_state':'enabled','campaign_state':'enabled',
                                   'ad_group_state':'enabled'}]
    probes = build_probe_candidates(board)
    assert list(probes) == ['sif-probe:p1:gap']
    assert probes['sif-probe:p1:gap']['source'] == 'sif_competitor_gap'
    assert probes['sif-probe:p1:gap']['weekly_volume'] is None


def test_old_rejected_competitor_gap_does_not_survive_as_trial_intent():
    board = _board()
    board['products']['s1|UK|B012345678']['keyword_state']['terms'].append({
        'id':'old-gap','keyword':'adult chef knife','normalized':'adult chef knife',
        'sources':['sif_competitor_gap'],'current_competitor_gap':False,
        'weekly_volume':None,'tracking':{'state':'candidate'},'internal_evidence':None})
    probes = build_probe_candidates(board)
    assert 'sif-probe:p1:old-gap' not in probes


def test_own_sif_term_without_positive_volume_is_not_a_trial_intent():
    board = _board()
    board['products']['s1|UK|B012345678']['keyword_state']['terms'][0]['weekly_volume'] = None
    assert build_probe_candidates(board) == {}


def test_probe_intent_requires_rationale_and_cannot_be_frozen_as_exact(tmp_path):
    board = _board()
    run = tmp_path / board['run_id']
    run.mkdir()
    board_bytes = json.dumps(board).encode('utf-8')
    (run / 'board.json').write_bytes(board_bytes)
    (run / 'manifest.json').write_text(json.dumps({
        'state': 'complete', 'run_id': board['run_id'],
        'batch_sha256': hashlib.sha256(board_bytes).hexdigest(),
    }), encoding='utf-8')
    render_board(run / 'board.json', run / 'board.html')
    previous = (run / 'board.html').read_bytes()
    render_board(run / 'board.json', run / 'board-ads-v2.html')
    assert (run / 'board.html').read_bytes() == previous
    previous_v2 = (run / 'board-ads-v2.html').read_bytes()
    render_board(run / 'board.json', run / 'board-ads-v3.html')
    assert (run / 'board-ads-v2.html').read_bytes() == previous_v2
    app = create_app(run, tmp_path / 'state.sqlite3', html_name='board-ads-v3.html')

    async def exercise():
        headers = {'X-Local-Session': app.state.session_token,
                   'Origin': 'http://127.0.0.1:8767'}
        async with AsyncClient(transport=ASGITransport(app), base_url='http://127.0.0.1:8767') as client:
            assert '关键词雷达' in (await client.get('/')).text
            body = {'run_id': board['run_id'], 'action_key': 'sif-probe:p1:sif-only',
                    'profile_id': 'p1', 'value': 'accept', 'expected_version': 0}
            assert (await client.post('/api/decisions', json=body, headers=headers)).status_code == 400
            accepted = await client.post('/api/decisions', json={**body,
                'note': '与本品剪刀用途相关，申请精准试投核验'}, headers=headers)
            assert accepted.status_code == 200
            assert accepted.json()['bid'] is None
            assert (await client.post('/api/decisions', json={**body, 'expected_version': 1,
                'note': '重复', 'bid': 0.5}, headers=headers)).status_code == 400
            assert (await client.post('/api/decisions', json={**body,
                'action_key': 'sif-probe:p1:has-data', 'expected_version': 1,
                'note': '错配'}, headers=headers)).status_code == 404
    asyncio.run(exercise())
