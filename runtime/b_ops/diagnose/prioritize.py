"""Today-first issue ordering; data gaps are not business alarms."""


SEVERITY = {"critical": 100, "high": 75, "medium": 50, "low": 25, "gap": 0}


def prioritize(issues: list[dict]) -> list[dict]:
    return sorted(issues, key=lambda issue: (
        -SEVERITY.get(issue.get("severity"), 0),
        -int(bool(issue.get("actionability"))),
        {"inventory": 0, "advertising": 1, "listing": 2}.get(issue.get("domain"), 3),
        issue.get("title", ""),
    ))
