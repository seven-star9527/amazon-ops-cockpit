from datetime import datetime, timedelta, timezone

from b_ops.actions.batch import build_batch
from b_ops.actions.execute import execute_batch
from b_ops.actions.followup import assess_followup
from b_ops.actions.preflight import validate_preflight
from b_ops.model.storage import StateStore


NOW=datetime(2026,10,12,13,0,tzinfo=timezone.utc)


class FakeLingxing:
    def __init__(self):self.calls=[]
    def call(self,tool,params):
        self.calls.append((tool,params))
        return {'code':1,'success':True,'data':{'success':[{'index':0,'target':{'targetId':'remote-1'}}],'error':[]}}


def test_operator_choice_agent_review_frozen_write_receipt_and_followup(tmp_path):
    store=StateStore(tmp_path/'state.sqlite3')
    action={'action_key':'shared-negative','kind':'negative','profile_id':'123','sponsored_type':'sp',
            'campaign_id':'c1','ad_group_id':'g1','query':'bad term','executable':True,
            'existing_negative':False,'affected_asins':['B012345678','B098765432'],
            'clicks':14,'spend':18,'orders':0,'sales':0}
    board={'run_id':'b-test','fetched_at':(NOW-timedelta(hours=1)).isoformat(),
           'products':{},'actions':[action]}
    accepted=store.save_decision('b-test','shared-negative','123','accept','',expected_version=0)
    assert accepted['version']==1
    review={'run_id':'b-test','batch_sha256':'source-hash','decision_version':store.decision_version('b-test'),
            'approved_action_keys':['shared-negative'],'reviewed_at':NOW.isoformat()}
    batch=build_batch(board,store.latest_decisions('b-test'),review,'123',
                      manifest={'batch_sha256':'source-hash'},now=NOW)
    assert len(batch['items'])==1 and len(batch['items'][0]['affected_asins'])==2
    preflight={'batch_id':batch['batch_id'],'content_sha256':batch['content_sha256'],'checked_at':NOW.isoformat(),
               'items':[{'action_key':'shared-negative','group_active':True,'target_absent':True,
                         'source_tool':'advertising_get_negative_keywords','source_sha256':'a'*64}]}
    validate_preflight(batch,preflight,now=NOW)
    fake=FakeLingxing()
    receipt=execute_batch(batch,f"{batch['batch_id']}:{batch['content_sha256']}",fake,now=NOW)
    assert len(fake.calls)==1
    assert receipt['items'][0]['status']=='accepted' and receipt['items'][0]['readback_status']=='pending'
    follow=assess_followup({'action_key':'shared-negative','kind':'negative','query':'bad term',
                            'profile_id':'123','ad_group_id':'g1','before':{'spend':18}},
                           [{'query':'bad term','profile_id':'123','ad_group_id':'g1','spend':3}],days_elapsed=8)
    assert follow['state']=='observed_change'
