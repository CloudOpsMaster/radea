"""Flaky-test analysis across several JUnit XML runs (article 06).

Looks at patterns over many runs instead of one log: a test that both passes and fails on the
same code is flaky, one that always fails is broken. The mechanism is only ever a hint.
"""

import re
import xml.etree.ElementTree as ET  # noqa: S405 - DOCTYPE/ENTITY are rejected before parsing
from dataclasses import dataclass, field

from radea.static_review.files import Source
from radea.static_review.findings import Finding, quote

HINTS = {
    "timeout": re.compile(r"(?i)time[d ]?out|deadline|timed out"),
    "network": re.compile(r"(?i)connection (?:refused|reset)|unreachable|ECONN|no route to host"),
    "concurrency": re.compile(r"(?i)race|deadlock|concurrent|ConcurrentModification"),
    "resources": re.compile(r"(?i)OutOfMemory|\bOOM\b|no space left|too many open files"),
    "shared state": re.compile(r"(?i)already exists|duplicate|stale|not empty|leftover"),
    "async wait": re.compile(r"(?i)eventually|not (?:yet )?ready|await|poll"),
    "time or locale": re.compile(r"(?i)timezone|clock|daylight|locale"),
}
PASS, FAIL, SKIP, FLAKY = "pass", "fail", "skip", "flaky"


@dataclass
class TestHistory:
    test: str
    outcomes: list[str] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)
    first_failure_run: str = ""

    @property
    def runs(self) -> int:
        return sum(1 for o in self.outcomes if o != SKIP)

    @property
    def failures(self) -> int:
        return sum(1 for o in self.outcomes if o in (FAIL, FLAKY))

    @property
    def flips(self) -> int:
        seq = [o for o in self.outcomes if o != SKIP]
        return sum(1 for a, b in zip(seq, seq[1:], strict=False) if (a == PASS) != (b == PASS))


def parse_run(src: Source, *, reject_duplicates: bool = False) -> dict[str, tuple[str, str]]:
    """Map test id to (outcome, message) for one JUnit file."""
    upper = src.text.upper()
    if "<!DOCTYPE" in upper or "<!ENTITY" in upper:
        raise ValueError("DOCTYPE and entities are not accepted in JUnit XML")
    try:
        # DOCTYPE and ENTITY declarations were rejected above, so no entity can expand.
        root = ET.fromstring(src.text)  # nosec B314
    except ET.ParseError:
        raise ValueError("not valid XML") from None
    cases = root.iter("testcase")
    results: dict[str, tuple[str, str]] = {}
    for case in cases:
        name = f"{case.get('classname', '')}::{case.get('name', '?')}".strip(":")
        if reject_duplicates and name in results:
            raise ValueError("JUnit report contains duplicate test identifiers")
        kinds = {child.tag: child for child in case}
        message = ""
        if "failure" in kinds or "error" in kinds:
            node = kinds.get("failure", kinds.get("error"))
            message = (node.get("message") or (node.text or "")).strip() if node is not None else ""
            outcome = FAIL
        elif "flakyFailure" in kinds or "flakyError" in kinds:
            node = kinds.get("flakyFailure", kinds.get("flakyError"))
            message = (node.get("message") or "").strip() if node is not None else ""
            outcome = FLAKY
        elif "skipped" in kinds:
            outcome = SKIP
        else:
            outcome = PASS
        results[name] = (outcome, message.splitlines()[0] if message else "")
    if not results:
        raise ValueError("no test cases found")
    return results


def analyse(runs: list[Source], min_runs: int) -> tuple[list[Finding], dict]:
    histories: dict[str, TestHistory] = {}
    for src in runs:
        for test, (outcome, message) in parse_run(src).items():
            history = histories.setdefault(test, TestHistory(test))
            history.outcomes.append(outcome)
            if outcome in (FAIL, FLAKY):
                history.messages.append(message)
                history.first_failure_run = history.first_failure_run or src.path
    findings: list[Finding] = []
    flaky = broken = 0
    ranked = sorted(
        histories.values(), key=lambda h: (-(h.failures / max(h.runs, 1)) * h.flips, h.test)
    )
    for history in ranked:
        if history.runs == 0 or history.failures == 0:
            continue
        message = next((m for m in history.messages if m), "")
        hints = [
            name for name, pattern in HINTS.items() if pattern.search(" ".join(history.messages))
        ]
        counts = f"failed {history.failures}/{history.runs} runs, {history.flips} flip(s)"
        mixed = FLAKY in history.outcomes or (PASS in history.outcomes and history.failures)
        if mixed:
            flaky += 1
            detail = counts + (f"; possible: {', '.join(hints)}" if hints else "")
            findings.append(
                Finding(
                    "FLAKY001",
                    history.test,
                    history.first_failure_run,
                    None,
                    quote(message),
                    detail,
                    order=len(findings),
                )  # fmt: skip
            )
        elif history.runs >= max(min_runs, 2):
            broken += 1
            findings.append(
                Finding(
                    "FLAKY002",
                    history.test,
                    history.first_failure_run,
                    None,
                    quote(message),
                    counts,
                    order=len(findings),
                )  # fmt: skip
            )
    extra = {
        "runs": len(runs),
        "tests": len(histories),
        "flaky_tests": flaky,
        "consistently_failing_tests": broken,
    }
    return findings, extra
