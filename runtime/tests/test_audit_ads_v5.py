from scripts.audit_run import validate_ad_actions, validate_transport_provenance


def test_v5_audit_accepts_group_exact_and_target_bid_but_rejects_bad_identity():
    exact={"action_key":"exact-group|p1|c1|g1|word","kind":"exact","profile_id":"p1",
           "campaign_id":"c1","ad_group_id":"g1","query":"word","affected_asins":["B0CHILD001","B0CHILD002"],
           "parent_scope":"verified_same_parent","reviewable":True,"executable":False,
           "processed_status":"","blocked_reason":"","source_count":1,
           "suggested_bid":.5,"exact_plan":{"target_required":True,"promoted_asin":""}}
    bid={"action_key":"bid-target|p1|c1|g1|t1","kind":"bid_review","profile_id":"p1",
         "campaign_id":"c1","ad_group_id":"g1","target_id":"t1","query":"word",
         "affected_asins":["B0CHILD001","B0CHILD002"],"reviewable":True,
         "executable":False,"blocked_reason":"",
         "direction":"consider_raise","effective_bid_ceiling":1.0,
         "bid_evidence":{"target_id":"t1","base_bid":.5,"budget":30},
         "rank_evidence":{"reference_asin":"B0CHILD001","children":{"B0CHILD001":{"state":"verified",
              "natural_latest":30,"advertising_latest":22,
              "natural_week_days":[5,5],"advertising_week_days":[5,5]},
                                       "B0CHILD002":{"state":"verified",
              "natural_week_days":[5,5],"advertising_week_days":[5,5]}}}}
    validate_ad_actions([exact,bid])
    try:
        validate_ad_actions([{**bid,"target_id":""}])
    except AssertionError:
        pass
    else:
        raise AssertionError("target ID must not be optional")
    try:
        validate_ad_actions([{**bid,"rank_evidence":{"reference_asin":"B0CHILD001","children":{
            **bid["rank_evidence"]["children"],"B0CHILD001":{"state":"insufficient_days",
            "advertising_latest":22,"advertising_week_days":[0,1]}}}}])
    except AssertionError:
        pass
    else:
        raise AssertionError("one-day rank is insufficient for a review")


def test_resumed_sif_audit_distinguishes_reused_raw_from_new_live_calls():
    source='b-20261014-raw'
    status={'sif_transport':{'state':'same_day_b_raw_resume_live',
                             'source_run_id':source,'reused_calls':1,'live_calls':1}}
    calls=[{'provider':'sif','replayed_from_b_run':source},
           {'provider':'sif'}, {'provider':'lingxing','replayed_from_b_run':'b-other'}]
    validate_transport_provenance(status,calls)
    try:
        validate_transport_provenance(status,[{**calls[0]},{**calls[1],'replayed_from_b_run':source}])
    except AssertionError:
        pass
    else:
        raise AssertionError('a live SIF call mislabeled as replay must fail audit')


def test_audit_accepts_directional_bid_without_theoretical_ceiling_but_requires_rank_days():
    bid={"action_key":"bid-target|p1|c1|g1|t1","kind":"bid_review","profile_id":"p1",
         "campaign_id":"c1","ad_group_id":"g1","target_id":"t1","query":"word",
         "affected_asins":["B0CHILD001","B0CHILD002"],"reviewable":True,
         "executable":False,"blocked_reason":"","direction":"consider_lower",
         "effective_bid_ceiling":None,
         "bid_evidence":{"target_id":"t1","base_bid":.5,"budget":30},
         "rank_evidence":{"reference_asin":"B0CHILD001","review_basis":"directional",
                          "children":{"B0CHILD001":{"state":"insufficient_days",
                                      "advertising_latest":17,"advertising_week_days":[1,3],
                                      "natural_week_days":[0,0]},"B0CHILD002":None}}}
    validate_ad_actions([bid])
    try:
        validate_ad_actions([{**bid,"rank_evidence":{"children":{"B0CHILD001":{
            "advertising_latest":17,"advertising_week_days":[0,1]},"B0CHILD002":None}}}])
    except AssertionError:
        pass
    else:
        raise AssertionError('one-day ranking cannot support a bid direction')


def test_extended_complete_sif_audit_uses_the_same_call_level_provenance_gate():
    status={'sif_transport':{'state':'same_day_b_complete_extend_live',
                             'source_run_id':'b-20261014-complete','reused_calls':2,'live_calls':1}}
    calls=[{'provider':'sif','replayed_from_b_run':'b-20261014-complete'},
           {'provider':'sif','replayed_from_b_run':'b-20261014-complete'},
           {'provider':'sif'}]
    validate_transport_provenance(status,calls)
    try:
        validate_transport_provenance(status,calls[:-1])
    except AssertionError:
        pass
    else:
        raise AssertionError('missing live call must fail extended-source audit')
