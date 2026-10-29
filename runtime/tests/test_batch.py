from datetime import datetime, timezone, timedelta

import pytest

from b_ops.actions.batch import build_batch


NOW = datetime(2026,10,12,13,0,tzinfo=timezone.utc)


def board():
    return {'run_id':'b-run','fetched_at':(NOW-timedelta(hours=2)).isoformat(),
            'batch_sha256':'source-sha','products':{},
            'actions':[
                {'action_key':'n1','kind':'negative','profile_id':'123','sponsored_type':'sp','campaign_id':'c1','ad_group_id':'g1','query':'bad term','executable':True,'affected_asins':['B012345678','B098765432'],'existing_negative':False},
                {'action_key':'e1','kind':'exact','profile_id':'123','sponsored_type':'sp','campaign_id':'c1','ad_group_id':'g1','query':'good term','executable':True,'affected_asins':['B012345678'],'existing_exact':False,'suggested_bid':0.63},
            ]}


def test_batch_freezes_reviewed_negative_scope_once():
    source=board()
    decisions={'n1':{'value':'accept','version':1,'profile_id':'123'}}
    review={'run_id':'b-run','batch_sha256':'source-sha','decision_version':1,'approved_action_keys':['n1']}
    result=build_batch(source,decisions,review,'123',now=NOW)
    assert len(result['items']) == 1
    assert {row['tool'] for row in result['items']} == {'advertising_add_negative_keywords'}
    assert result['content_sha256']


def test_stale_review_or_run_blocks_batch():
    source=board()
    decisions={'n1':{'value':'accept','version':1,'profile_id':'123'}}
    review={'run_id':'b-run','batch_sha256':'wrong','decision_version':1,'approved_action_keys':['n1']}
    with pytest.raises(ValueError,match='hash'):
        build_batch(source,decisions,review,'123',now=NOW)
    review['batch_sha256']='source-sha'
    with pytest.raises(ValueError,match='stale'):
        build_batch(source,decisions,review,'123',now=NOW+timedelta(days=2))


def test_unapproved_shared_action_never_becomes_two_writes():
    source=board()
    decisions={'n1':{'value':'accept','version':1,'profile_id':'123'}}
    review={'run_id':'b-run','batch_sha256':'source-sha','decision_version':1,'approved_action_keys':[]}
    with pytest.raises(ValueError,match='approved'):
        build_batch(source,decisions,review,'123',now=NOW)


def test_integrated_exact_plan_can_be_reviewed_but_not_frozen_for_remote_write():
    source=board()
    source['actions'][1].update({'executable':False,'reviewable':True,'exact_plan':{'object_type':'keyword'}})
    decisions={'e1':{'value':'accept','version':1,'profile_id':'123','bid':0.71}}
    review={'run_id':'b-run','batch_sha256':'source-sha','decision_version':1,'approved_action_keys':['e1']}
    with pytest.raises(ValueError,match='not executable'):
        build_batch(source,decisions,review,'123',now=NOW)
