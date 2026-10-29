import copy
from datetime import datetime, timezone

import pytest

from b_ops.actions.execute import execute_batch, WriteOutcomeUnknown
from b_ops.actions.batch import canonical_hash


NOW = datetime(2026, 10, 12, 13, 0, tzinfo=timezone.utc)


def frozen():
    batch = {"schema": "amazon-ops-b/frozen-action-batch/1", "run_id": "b-test",
             "source_sha256": "abc", "profile_id": "123", "decision_version": 2,
             "expires_at": "2026-10-13T11:00:00+00:00",
             "items": [{"action_key": "k1", "tool": "advertising_add_negative_keywords",
                        "payload": {"profileId": 123, "campaignId": "c", "adGroupId": "g",
                                    "keyword": "bad", "matchType": "negativeExact", "state": "ENABLED"}},
                       {"action_key": "k2", "tool": "advertising_add_negative_targets",
                        "payload": {"profileId": 123, "campaignId": "c", "adGroupId": "g",
                                    "asin": "B012345678", "state": "ENABLED"}}]}
    batch["content_sha256"] = canonical_hash(batch)
    batch["batch_id"] = f"b-test-{batch['content_sha256'][:12]}"
    return batch


class FakeWriter:
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    def call(self, tool, params):
        self.calls.append((tool, params))
        if self.fail:
            raise WriteOutcomeUnknown("timeout")
        return {"code": 1, "success": True,
                "data": {"success": [{"index": 0, "target": {"targetId": "target-1"}}], "error": []}}


def test_unconfirmed_or_tampered_batch_never_writes():
    batch=frozen(); writer=FakeWriter()
    with pytest.raises(ValueError, match='confirmation'):
        execute_batch(batch, 'continue', writer, now=NOW)
    assert writer.calls == []
    tampered=copy.deepcopy(batch);tampered['items'][0]['payload']['keyword']='other'
    with pytest.raises(ValueError, match='hash'):
        execute_batch(tampered, f"{batch['batch_id']}:{batch['content_sha256']}", writer, now=NOW)
    assert writer.calls == []


def test_confirmed_items_use_exact_lingxing_schema_and_report_accepted_not_verified():
    batch=frozen();writer=FakeWriter()
    receipt=execute_batch(batch,f"{batch['batch_id']}:{batch['content_sha256']}",writer,now=NOW)
    assert len(writer.calls)==2
    assert writer.calls[0][1]['negativeKeywords'][0]['adGroupId']=='g'
    assert writer.calls[1][1]['asins'][0]['asin']=='B012345678'
    assert [item['status'] for item in receipt['items']]==['accepted','accepted']
    assert all(item['readback_status']=='pending' for item in receipt['items'])


def test_unknown_response_is_not_retried_and_locks_remaining_items():
    batch=frozen();writer=FakeWriter(fail=True)
    receipt=execute_batch(batch,f"{batch['batch_id']}:{batch['content_sha256']}",writer,now=NOW)
    assert len(writer.calls)==1
    assert [item['status'] for item in receipt['items']]==['unknown','not_submitted']


def test_stale_batch_blocks_before_call():
    batch=frozen();writer=FakeWriter()
    with pytest.raises(ValueError,match='stale'):
        execute_batch(batch,f"{batch['batch_id']}:{batch['content_sha256']}",writer,
                      now=datetime(2026,10,14,tzinfo=timezone.utc))
    assert writer.calls==[]


def test_even_a_forged_exact_frozen_batch_is_rejected_before_remote_call():
    batch=frozen();writer=FakeWriter()
    batch['items'][1]['tool']='advertising_sp_add_keywords'
    batch['content_sha256']=canonical_hash({key:value for key,value in batch.items() if key not in {'batch_id','content_sha256'}})
    batch['batch_id']=f"b-test-{batch['content_sha256'][:12]}"
    with pytest.raises(ValueError,match='unapproved write tool'):
        execute_batch(batch,f"{batch['batch_id']}:{batch['content_sha256']}",writer,now=NOW)
    assert writer.calls==[]
