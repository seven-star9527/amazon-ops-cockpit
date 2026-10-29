import json
import asyncio
import hashlib

from httpx import ASGITransport, AsyncClient

from b_ops.render import render_board
from b_ops.server import create_app
from b_ops.model.storage import StateStore


def test_review_server_accepts_independent_v4_html(tmp_path):
    run = tmp_path / 'b-v4'
    run.mkdir()
    board = {'run_id': 'b-v4', 'products': {}, 'actions': [], 'coverage': {}, 'status': {}}
    raw = json.dumps(board).encode('utf-8')
    (run / 'board.json').write_bytes(raw)
    (run / 'manifest.json').write_text(json.dumps({'state': 'complete', 'run_id': 'b-v4',
        'batch_sha256': hashlib.sha256(raw).hexdigest()}), encoding='utf-8')
    render_board(run / 'board.json', run / 'board-ads-v4.html')
    app = create_app(run, tmp_path / 'state.sqlite3', html_name='board-ads-v4.html')
    assert app.state.run_id == 'b-v4'


def test_review_server_accepts_independent_v5_html(tmp_path):
    run=tmp_path/'b-v5'
    run.mkdir()
    board={'run_id':run.name,'products':{},'actions':[],'coverage':{},'status':{}}
    raw=json.dumps(board).encode('utf-8')
    (run/'board.json').write_bytes(raw)
    (run/'manifest.json').write_text(json.dumps({'state':'complete','run_id':run.name,
        'batch_sha256':hashlib.sha256(raw).hexdigest()}),encoding='utf-8')
    render_board(run/'board.json',run/'board-ads-v5.html')
    assert create_app(run,tmp_path/'state.sqlite3',html_name='board-ads-v5.html').state.run_id==run.name


def test_review_server_accepts_independent_v7_html(tmp_path):
    run=tmp_path/'b-v7'
    run.mkdir()
    board={'run_id':run.name,'products':{},'actions':[],'coverage':{},'status':{}}
    raw=json.dumps(board).encode('utf-8')
    (run/'board.json').write_bytes(raw)
    (run/'manifest.json').write_text(json.dumps({'state':'complete','run_id':run.name,
        'batch_sha256':hashlib.sha256(raw).hexdigest()}),encoding='utf-8')
    render_board(run/'board.json',run/'board-ads-v7.html')
    assert create_app(run,tmp_path/'state.sqlite3',html_name='board-ads-v7.html').state.run_id==run.name


def test_review_api_requires_local_token_origin_same_run_and_profile(tmp_path):
    run = tmp_path / 'b-test'
    run.mkdir()
    board = {'run_id':'b-test','products':{},'actions':[{'action_key':'a','profile_id':'p1','executable':True}],
             'coverage':{},'status':{}}
    board_bytes=json.dumps(board).encode('utf-8')
    (run/'board.json').write_bytes(board_bytes)
    (run/'manifest.json').write_text(json.dumps({'state':'complete','run_id':'b-test',
                                                'batch_sha256':hashlib.sha256(board_bytes).hexdigest()}),encoding='utf-8')
    render_board(run/'board.json',run/'board.html')
    app = create_app(run,tmp_path/'state.sqlite3')
    async def exercise():
        async with AsyncClient(transport=ASGITransport(app),base_url='http://127.0.0.1:8767') as client:
            assert 'window.B_REVIEW' in (await client.get('/')).text
            body = {'run_id':'b-test','action_key':'a','profile_id':'p1','value':'accept','note':'好','expected_version':0}
            assert (await client.post('/api/decisions',json=body)).status_code == 403
            headers = {'X-Local-Session':app.state.session_token,'Origin':'http://127.0.0.1:8767'}
            assert (await client.post('/api/decisions',json={**body,'profile_id':'p2'},headers=headers)).status_code == 400
            assert (await client.post('/api/decisions',json=body,headers={**headers,'Origin':'https://evil.invalid'})).status_code == 403
            assert (await client.post('/api/decisions',json=body,headers=headers)).status_code == 200
            assert (await client.post('/api/decisions',json=body,headers=headers)).status_code == 409
    asyncio.run(exercise())


def test_review_only_exact_accepts_plan_but_processed_action_cannot_be_accepted(tmp_path):
    run = tmp_path / 'b-exact-review'
    run.mkdir()
    board = {'run_id':'b-exact-review','products':{},'coverage':{},'status':{},
        'ad_keyword_targets':[
            {'profile_id':'p1','campaign_id':'c2','ad_group_id':'g2',
             'campaign_state':'enabled','ad_group_state':'enabled'}],
        'actions':[
        {'action_key':'exact','profile_id':'p1','kind':'exact','reviewable':True,'executable':False},
        {'action_key':'done','profile_id':'p1','kind':'negative','reviewable':False,
         'executable':False,'processed_status':'already_exact_negative'},
    ]}
    board_bytes=json.dumps(board).encode('utf-8')
    (run/'board.json').write_bytes(board_bytes)
    (run/'manifest.json').write_text(json.dumps({'state':'complete','run_id':board['run_id'],
        'batch_sha256':hashlib.sha256(board_bytes).hexdigest()}),encoding='utf-8')
    render_board(run/'board.json',run/'board.html')
    app=create_app(run,tmp_path/'state.sqlite3')
    async def exercise():
        headers={'X-Local-Session':app.state.session_token,'Origin':'http://127.0.0.1:8767'}
        async with AsyncClient(transport=ASGITransport(app),base_url='http://127.0.0.1:8767') as client:
            body={'run_id':board['run_id'],'action_key':'exact','profile_id':'p1','value':'accept',
                  'bid':0.51,'target_campaign_id':'c2','target_ad_group_id':'g2','expected_version':0}
            assert (await client.post('/api/decisions',json=body,headers=headers)).status_code==200
            assert (await client.post('/api/decisions',json={**body,'action_key':'done','expected_version':1},
                                      headers=headers)).status_code==400
    asyncio.run(exercise())


def test_bid_review_requires_operator_bid_and_never_becomes_executable(tmp_path):
    run=tmp_path/'b-bid-review'
    run.mkdir()
    board={'run_id':run.name,'products':{},'coverage':{},'status':{},'actions':[
        {'action_key':'bid-target|p1|c1|g1|t1','profile_id':'p1','kind':'bid_review',
         'reviewable':True,'executable':False,'target_id':'t1'}]}
    raw=json.dumps(board).encode('utf-8')
    (run/'board.json').write_bytes(raw)
    (run/'manifest.json').write_text(json.dumps({'state':'complete','run_id':run.name,
        'batch_sha256':hashlib.sha256(raw).hexdigest()}),encoding='utf-8')
    render_board(run/'board.json',run/'board.html')
    app=create_app(run,tmp_path/'state.sqlite3')
    async def exercise():
        headers={'X-Local-Session':app.state.session_token,'Origin':'http://127.0.0.1:8767'}
        async with AsyncClient(transport=ASGITransport(app),base_url='http://127.0.0.1:8767') as client:
            body={'run_id':run.name,'action_key':'bid-target|p1|c1|g1|t1','profile_id':'p1',
                  'value':'accept','expected_version':0}
            assert (await client.post('/api/decisions',json=body,headers=headers)).status_code==400
            assert (await client.post('/api/decisions',json={**body,'bid':.55},headers=headers)).status_code==200
    asyncio.run(exercise())


def test_tracking_api_stages_next_run_change_without_mutating_board(tmp_path):
    run = tmp_path / 'b-track'
    run.mkdir()
    product = {'key':'s1|US|B012345678','sid':'s1','site':'US','asin':'B012345678',
               'status':'1','name':'儿童剪刀','weeks':[],'issues':[],'keyword_state':{'terms':[]}}
    board = {'run_id':'b-track','products':{product['key']:product},'actions':[],
             'coverage':{},'status':{}}
    board_bytes=json.dumps(board).encode('utf-8')
    (run/'board.json').write_bytes(board_bytes)
    (run/'manifest.json').write_text(json.dumps({'state':'complete','run_id':'b-track',
        'batch_sha256':hashlib.sha256(board_bytes).hexdigest()}),encoding='utf-8')
    render_board(run/'board.json',run/'board.html')
    app=create_app(run,tmp_path/'state.sqlite3')
    async def exercise():
        headers={'X-Local-Session':app.state.session_token,'Origin':'http://127.0.0.1:8767'}
        async with AsyncClient(transport=ASGITransport(app),base_url='http://127.0.0.1:8767') as client:
            request={'run_id':'b-track','sid':'s1','asin':'B012345678','keyword':'kids scissors',
                     'action':'add','expected_version':0}
            assert (await client.post('/api/tracking',json=request)).status_code == 403
            assert (await client.post('/api/tracking',json={**request,'sid':'s2'},headers=headers)).status_code == 400
            result=await client.post('/api/tracking',json=request,headers=headers)
            assert result.status_code == 200
            assert result.json()['pending'] == 'add'
            assert (await client.get('/api/tracking',params={'sid':'s1','asin':'B012345678'},headers=headers)).json()['terms'][0]['tracking']['pending'] == 'add'
            assert (await client.post('/api/tracking',json=request,headers=headers)).status_code == 409
            assert (await client.post('/api/sif-priority',json={'run_id':'b-track','sid':'s1',
                'asin':'B012345678','active':True,'expected_version':1},headers=headers)).status_code == 200
    asyncio.run(exercise())
    assert (run/'board.json').read_bytes() == board_bytes
    assert StateStore(tmp_path/'state.sqlite3').sif_priority_state(product['key'])['pending'] == 1


def test_tracking_bulk_api_is_scoped_and_atomic(tmp_path):
    run=tmp_path/'b-bulk'
    run.mkdir()
    product={'key':'s1|US|B012345678','sid':'s1','site':'US','asin':'B012345678',
             'status':'1','name':'测试','weeks':[],'issues':[],'keyword_state':{'terms':[]}}
    board={'run_id':run.name,'products':{product['key']:product},'actions':[],'coverage':{},'status':{}}
    raw=json.dumps(board).encode()
    (run/'board.json').write_bytes(raw)
    (run/'manifest.json').write_text(json.dumps({'state':'complete','run_id':run.name,
        'batch_sha256':hashlib.sha256(raw).hexdigest()}),encoding='utf-8')
    render_board(run/'board.json',run/'board.html')
    app=create_app(run,tmp_path/'state.sqlite3')
    async def exercise():
        headers={'X-Local-Session':app.state.session_token,'Origin':'http://127.0.0.1:8767'}
        body={'run_id':run.name,'sid':'s1','asin':'B012345678',
              'keywords':['kids knife','KIDS KNIFE','toddler knife'],'action':'add','expected_version':0}
        async with AsyncClient(transport=ASGITransport(app),base_url='http://127.0.0.1:8767') as client:
            assert (await client.post('/api/tracking/bulk',json=body)).status_code==403
            assert (await client.post('/api/tracking/bulk',json={**body,'sid':'other'},headers=headers)).status_code==400
            invalid=await client.post('/api/tracking/bulk',json={**body,'keywords':['good term','B012345678']},headers=headers)
            assert invalid.status_code==400
            result=await client.post('/api/tracking/bulk',json=body,headers=headers)
            assert result.status_code==200 and result.json()['accepted']==2
            assert all(row['tracking']['pending']=='add' for row in result.json()['terms'])
            assert (await client.post('/api/tracking/bulk',json=body,headers=headers)).status_code==409
    asyncio.run(exercise())
    assert len(StateStore(tmp_path/'state.sqlite3').list_keywords('US','B012345678',sid='s1'))==2


def test_competitor_api_is_parent_scoped_and_next_run_only(tmp_path):
    run = tmp_path / 'b-competitor'
    run.mkdir()
    product = {'key':'s1|UK|B0FGTVP62B','sid':'s1','site':'UK','asin':'B0FGTVP62B',
               'parent_asin':'B0PARENT01','status':'1','name':'儿童套装','weeks':[],
               'issues':[],'keyword_state':{'terms':[]}}
    board = {'run_id':run.name,'products':{product['key']:product},'actions':[],
             'coverage':{},'status':{}}
    raw=json.dumps(board).encode('utf-8')
    (run/'board.json').write_bytes(raw)
    (run/'manifest.json').write_text(json.dumps({'state':'complete','run_id':run.name,
                                                'batch_sha256':hashlib.sha256(raw).hexdigest()}),encoding='utf-8')
    render_board(run/'board.json',run/'board.html')
    app=create_app(run,tmp_path/'state.sqlite3')
    async def exercise():
        headers={'X-Local-Session':app.state.session_token,'Origin':'http://127.0.0.1:8767'}
        async with AsyncClient(transport=ASGITransport(app),base_url='http://127.0.0.1:8767') as client:
            body={'run_id':run.name,'sid':'s1','asin':'B0FGTVP62B','competitor_asin':'B0CHXTHK7N',
                  'action':'add','expected_version':0}
            assert (await client.post('/api/competitors',json=body)).status_code==403
            response=await client.post('/api/competitors',json=body,headers=headers)
            assert response.status_code==200
            assert response.json()['competitors'][0]['pending']=='add'
            assert response.json()['competitors'][0]['active']==0
            assert (await client.post('/api/competitors',json=body,headers=headers)).status_code==409
            assert (await client.get('/api/competitors',params={'sid':'s1','asin':'B0FGTVP62B'},
                                     headers=headers)).json()['parent_asin']=='B0PARENT01'
    asyncio.run(exercise())


def test_manual_asin_sif_query_is_scoped_and_keeps_board_immutable(tmp_path):
    run = tmp_path / 'b-manual'
    run.mkdir()
    product = {'key':'s1|US|B012345678','sid':'s1','site':'US','asin':'B012345678',
               'status':'1','name':'儿童剪刀','weeks':[],'issues':[],'keyword_state':{'terms':[]}}
    board = {'run_id':'b-manual','as_of_date':'2026-10-13','products':{product['key']:product},
             'actions':[],'coverage':{},'status':{}}
    board_bytes=json.dumps(board).encode('utf-8')
    (run/'board.json').write_bytes(board_bytes)
    (run/'manifest.json').write_text(json.dumps({'state':'complete','run_id':'b-manual',
        'batch_sha256':hashlib.sha256(board_bytes).hexdigest()}),encoding='utf-8')
    render_board(run/'board.json',run/'board.html')

    class FakeSif:
        def call(self, tool, params):
            if tool == 'market_get_asin_keyword_signals':
                return {'top_keywords':[{'keyword':'kids scissors','organic_rank':12,'sp_rank':'p1,9/12'}]}
            if tool == 'market_get_keyword_history':
                return {'keywords':[{'keyword':'kids scissors','latest':{'volume':1600,'date':'2026-W41'}}]}
            if tool == 'ads_get_asin_campaign_contribution_overview':
                return {'campaigns':[]}
            raise AssertionError(tool)

    app=create_app(run,tmp_path/'state.sqlite3',sif_client=FakeSif())
    async def exercise():
        headers={'X-Local-Session':app.state.session_token,'Origin':'http://127.0.0.1:8767'}
        async with AsyncClient(transport=ASGITransport(app),base_url='http://127.0.0.1:8767') as client:
            body={'run_id':'b-manual','sid':'s1','asin':'B012345678'}
            assert (await client.post('/api/sif-query',json=body)).status_code == 403
            assert (await client.post('/api/sif-query',json={**body,'asin':'B098765432'},headers=headers)).status_code == 400
            result=await client.post('/api/sif-query',json=body,headers=headers)
            assert result.status_code == 200
            term=result.json()['terms'][0]
            assert result.json()['run_id']=='b-manual'
            assert term['keyword']=='kids scissors' and term['tracking']['state']=='active'
            assert term['weekly_volume']==1600
            assert result.json()['rank_state']=='no_campaign'
            persisted=await client.get('/api/sif-supplement',params={'sid':'s1','asin':'B012345678'},headers=headers)
            assert persisted.status_code==200 and persisted.json()['query_id']==result.json()['query_id']
    asyncio.run(exercise())
    assert (run/'board.json').read_bytes()==board_bytes
    assert list((run/'supplements').glob('*/summary.json'))
