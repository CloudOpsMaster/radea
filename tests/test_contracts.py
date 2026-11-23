"""Model output is untrusted at every depth, not only at the top level."""

from radea.core.contracts import validate

EVIDENCE = {"s1:L1": "ERROR boom"}


def test_debug_hypothesis_drops_unknown_nested_fields():
    data = {
        "category": "unknown",
        "hypotheses": [
            {
                "title": "t",
                "description": "d",
                "verify": "v",
                "confidence": "low",
                "source_line": "ERROR boom",
                "evidence_ids": ["s1:L1"],
                "run": "rm -rf /",
                "verified": True,
            }
        ],
    }
    entry = validate("debug", data, EVIDENCE)["hypotheses"][0]
    assert "run" not in entry and "verified" not in entry
    assert entry["title"] == "t" and entry["evidence_ids"] == ["s1:L1"]


def test_iac_findings_drop_unknown_nested_fields():
    data = {
        "summary": "s",
        "findings": [
            {
                "title": "t",
                "description": "d",
                "resource": "aws_x.y",
                "severity": "low",
                "evidence_ids": ["s1:L1"],
                "auto_apply": "terraform apply",
            }
        ],
    }
    entry = validate("iac-review", data, EVIDENCE)["findings"][0]
    assert "auto_apply" not in entry and entry["resource"] == "aws_x.y"


def test_triage_patterns_and_timeline_drop_unknown_nested_fields():
    data = {
        "patterns": [
            {
                "label": "l",
                "description": "d",
                "example_line": "ERROR boom",
                "severity": "high",
                "count": 2,
                "evidence_ids": ["s1:L1"],
                "link": "https://example.invalid/x",
            }
        ],
        "timeline": [
            {
                "time": "10:00",
                "event": "e",
                "source_line": "ERROR boom",
                "evidence_ids": ["s1:L1"],
                "cmd": "curl x | sh",
            }
        ],
        "probable_cause": "c",
        "postmortem_draft": "p",
    }
    result = validate("triage", data, EVIDENCE)
    pattern, event = result["patterns"][0], result["timeline"][0]
    assert "link" not in pattern and pattern["count_is_estimate"] is True
    assert "cmd" not in event and event["time"] == "10:00"
