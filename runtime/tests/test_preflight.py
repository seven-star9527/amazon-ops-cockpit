from datetime import datetime, timezone, timedelta

import pytest

from b_ops.actions.preflight import validate_preflight


NOW=datetime(2026,10,12,13,0,tzinfo=timezone.utc)


def test_fresh_same_batch_remote_check_needed_for_every_item():
    batch={"batch_id":"b-x-hash","content_sha256":"hash","items":[{"action_key":"a"},{"action_key":"b"}]}
    check={"batch_id":"b-x-hash","content_sha256":"hash","checked_at":NOW.isoformat(),
           "items":[{"action_key":key,"group_active":True,"target_absent":True,"source_tool":"read_targets","source_sha256":"a"*64} for key in ('a','b')]}
    validate_preflight(batch,check,now=NOW+timedelta(minutes=4))
    check['items'][1]['target_absent']=False
    with pytest.raises(ValueError,match='duplicate'):
        validate_preflight(batch,check,now=NOW+timedelta(minutes=4))
    check['items'][1]['target_absent']=True
    with pytest.raises(ValueError,match='stale'):
        validate_preflight(batch,check,now=NOW+timedelta(minutes=20))
