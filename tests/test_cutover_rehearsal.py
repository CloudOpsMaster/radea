import pytest

from radea import cutover_rehearsal as rehearsal


@pytest.mark.parametrize(
    ("failure", "probe_failure", "passed", "stages"),
    [
        (100, None, True, [25, 50, 100, 0]),
        (None, 50, False, [25, 50, 0]),
    ],
)
def test_rehearsal_checks_live_probe_and_restores(
    monkeypatch, failure, probe_failure, passed, stages
):
    live_weight = 0
    applied = []
    monkeypatch.setattr(rehearsal.time, "sleep", lambda _: None)

    def rollout(*args, expected_weight):
        nonlocal live_weight
        weight, _, _, apply = args[-4:]
        assert expected_weight == live_weight
        if apply:
            applied.append(weight)
            live_weight = weight

    def probe(target, path, expected):
        assert path == "/ready"
        healthy = live_weight != probe_failure
        marker = b"candidate" if live_weight == 100 else b"stable"
        return healthy, healthy and (expected is None or expected == marker)

    monkeypatch.setattr(rehearsal, "rollout", rollout)
    monkeypatch.setattr(rehearsal, "_probe", probe)
    report = rehearsal.rehearse(
        ("kubeconfig", "local", "apps", "route", "stable", "candidate", 0),
        "http://localhost",
        "/ready",
        "stable",
        "candidate",
        (25, 50, 100),
        failure,
        3,
    )
    assert applied == stages
    assert report["passed"] is passed
    assert report["restored"]
    assert report["injected_failure"] is (failure is not None)
    assert report["events"][-1]["phase"] == "restore"
    assert live_weight == 0
