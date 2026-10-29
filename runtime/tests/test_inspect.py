import pytest

from b_ops.inspect import inspect_product


def test_inspection_is_one_store_child_asin_and_domain_only():
    board={'run_id':'b-test','fetched_at':'now','status':{},'products':{
        'one':{'key':'one','sid':'1','site':'UK','asin':'B012345678','name':'中文名','issues':[{'domain':'inventory'},{'domain':'advertising'}],
               'actions':[{'action_key':'a'}],'keyword_state':{'terms':[{'keyword':'term'}]},'weeks':[],'stock':{}},
        'two':{'key':'two','sid':'2','site':'UK','asin':'B012345678','name':'同 ASIN 另店','issues':[],'actions':[],'weeks':[],'stock':{}}}}
    packet=inspect_product(board,'1','B012345678',domain='inventory')
    assert packet['identity']['name']=='中文名'
    assert packet['issues']==[{'domain':'inventory'}]
    assert packet['actions']==[] and packet['keywords']==[]
    with pytest.raises(ValueError,match='exactly one'):
        inspect_product(board,'3','B012345678')
