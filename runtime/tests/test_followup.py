from datetime import datetime, timezone

from b_ops.actions.followup import assess_followup


def test_action_outcome_never_claims_causality_and_requires_comparable_evidence():
    item={"action_key":"a", "kind":"negative", "query":"bad term", "profile_id":"123",
          "ad_group_id":"g1", "before":{"spend":20,"clicks":15}}
    assert assess_followup(item, [], days_elapsed=3)["state"] == "not_due"
    assert assess_followup(item, [], days_elapsed=8)["state"] == "source_missing"
    after=[{"query":"bad term","profile_id":"123","ad_group_id":"g1","spend":4,"clicks":2}]
    result=assess_followup(item,after,days_elapsed=8)
    assert result["state"] == "observed_change"
    assert "造成" not in result["message"]
    assert assess_followup(item,after,days_elapsed=8,confounders=["售价变化"])["state"] == "confounded"
