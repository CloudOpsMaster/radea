"""Rehearse and restore one Gateway HTTPRoute with live availability probes."""

import http.client
import time
from urllib.parse import urlsplit

from radea.gateway_rollout import rollout
from radea.migration import _path


def _origin(url: str) -> tuple:
    origin = urlsplit(url)
    if (
        origin.scheme not in ("http", "https")
        or not origin.hostname
        or origin.username is not None
        or origin.password is not None
        or origin.query
        or origin.fragment
        or origin.path not in ("", "/")
    ):
        raise ValueError("Expected an HTTP(S) probe origin without credentials")
    connection = (
        http.client.HTTPSConnection if origin.scheme == "https" else http.client.HTTPConnection
    )
    return connection, origin.hostname, origin.port


def _probe(target: tuple, path: str, expected: bytes | None) -> tuple[bool, bool]:
    connection_type, hostname, port = target
    connection = connection_type(hostname, port, timeout=3)
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        healthy = 200 <= response.status < 300
        matches = healthy and (expected is None or response.read(len(expected) + 1) == expected)
        return healthy, matches
    except (OSError, http.client.HTTPException):
        return False, False
    finally:
        connection.close()


def rehearse(
    route: tuple[str, str, str, str, str, str, int],
    origin: str,
    path: str,
    stable_body: str,
    candidate_body: str,
    weights: tuple[int, ...],
    fail_at: int | None,
    samples: int,
) -> dict:
    if not 3 <= samples <= 120:
        raise ValueError("Specify between 3 and 120 probe samples per stage")
    if not weights or tuple(sorted(set(weights))) != weights or not 1 <= weights[0] <= 100:
        raise ValueError("Specify increasing candidate weights between 1 and 100")
    if weights[-1] != 100 or (fail_at is not None and fail_at not in weights):
        raise ValueError(
            "Specify a sequence ending at 100 and an optional failure at a listed step"
        )
    if (
        stable_body == candidate_body
        or not 1 <= len(stable_body.encode()) <= 256
        or not 1 <= len(candidate_body.encode()) <= 256
    ):
        raise ValueError("Specify two distinct probe response markers of at most 256 bytes")
    target = _origin(origin)
    path = _path(path)
    events: list[dict] = []

    def verify(weight: int, phase: str, expected: bytes | None = None) -> bool:
        matches = 0
        healthy = 0
        for index in range(samples):
            available, passed = _probe(target, path, expected)
            healthy += int(available)
            matches = matches + 1 if passed else 0
            if index + 1 < samples:
                time.sleep(0.25)
        passed = healthy == samples and matches >= 3
        events.append(
            {
                "phase": phase,
                "weight": weight,
                "passed": passed,
                "healthy_samples": healthy,
                "total_samples": samples,
            }
        )
        return passed

    def stage(weight: int, expected: int, apply: bool) -> None:
        rollout(*route, weight, None, None, apply, expected_weight=expected)

    stage(0, 0, False)
    baseline = verify(0, "baseline", stable_body.encode())
    current = 0
    forward = baseline
    injected = False
    restored = baseline
    if baseline:
        try:
            for weight in weights:
                stage(weight, current, True)
                current = weight
                marker = candidate_body.encode() if weight == 100 else None
                forward = verify(weight, "verify", marker)
                injected = forward and weight == fail_at
                if injected:
                    events.append({"phase": "inject_failure", "weight": weight})
                if not forward or injected:
                    break
        except (OSError, ValueError):
            events.append({"phase": "apply_failed"})
            forward = False
            restored = False
        finally:
            if current:
                try:
                    stage(0, current, True)
                    restored = verify(0, "restore", stable_body.encode())
                except (OSError, ValueError):
                    events.append({"phase": "restore_failed"})
                    restored = False
    passed = forward and restored and (fail_at is None or injected)
    return {
        "schema_version": "1.0",
        "command": "cutover-rehearse",
        "passed": passed,
        "restored": restored,
        "injected_failure": injected,
        "events": events,
    }
