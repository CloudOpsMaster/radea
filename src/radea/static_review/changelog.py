"""Changelog and release-note drafts from git history (article 08).

Quality is capped by commit hygiene, so the draft reports that hygiene too. It is always a
draft: a human approves it before anything is published.
"""

import re
import subprocess  # noqa: S404 - fixed argv, validated refs, no shell
from pathlib import Path

from radea.core.sanitizer import clean

REF = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_./~^@{}-]{0,200}$")
CONVENTIONAL = re.compile(
    r"^(?P<type>feat|fix|perf|refactor|docs|test|build|ci|chore|style|revert)"
    r"(?:\((?P<scope>[^)]+)\))?(?P<bang>!)?:\s*(?P<subject>.+)$"
)
MAINTENANCE = re.compile(
    r"(?i)automated version increase|Update Common Base OS|\bbump\b|renovate|dependabot|^merge\b"
)
TRACKING = re.compile(r"\b[A-Z][A-Z0-9]+-\d+\b|Tracking-Id:")
USER_FACING = ("feat", "fix", "perf")
ORDER = ("feat", "fix", "perf", "refactor", "docs", "test", "build", "ci", "chore", "other")
MAX_COMMITS = 500


def _validate_ref(name: str, value: str) -> str:
    if not REF.match(value) or ".." in value:
        raise ValueError(f"Invalid {name} reference")
    return value


def _git_log(repo: Path, start: str | None, end: str) -> list[tuple[str, str, str]]:
    revision = f"{start}..{end}" if start else end
    command = [
        "git", "--no-pager", "-C", str(repo), "log", "--no-merges", f"-n{MAX_COMMITS}",
        "--format=%H%x1f%s%x1f%b%x1e", revision, "--",
    ]  # fmt: skip
    try:
        done = subprocess.run(  # noqa: S603
            command,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
            env={"PATH": "/usr/bin:/bin:/usr/local/bin", "HOME": str(Path.home()), "LC_ALL": "C"},
        )
    except (OSError, subprocess.TimeoutExpired):
        raise ValueError("git is not available or timed out") from None
    if done.returncode:
        raise ValueError("git log failed: check the repository path and references")
    commits = []
    for record in done.stdout.split("\x1e"):
        parts = record.strip("\n").split("\x1f")
        if len(parts) == 3 and parts[0].strip():
            commits.append((parts[0].strip(), parts[1].strip(), parts[2].strip()))
    return commits


def build(repo: str, start: str | None, end: str) -> dict:
    path = Path(repo)
    if not path.is_dir():
        raise ValueError("Repository path is not a directory")
    start = _validate_ref("from", start) if start else None
    end = _validate_ref("to", end)
    groups: dict[str, list[dict]] = {name: [] for name in ORDER}
    breaking: list[dict] = []
    loose: list[str] = []
    untracked = conventional = 0
    commits = _git_log(path, start, end)
    for sha, subject, body in commits:
        match = CONVENTIONAL.match(subject)
        ids = sorted(set(re.findall(r"\b[A-Z][A-Z0-9]+-\d+\b", subject + "\n" + body)))
        if not TRACKING.search(subject + "\n" + body):
            untracked += 1
        conventional += bool(match)
        kind = match["type"] if match else "other"
        text = match["subject"] if match else subject
        if not match:
            if MAINTENANCE.search(subject):
                kind = "chore"
            else:
                loose.append(subject)
        entry = {
            "sha": sha[:10],
            "subject": text,
            "scope": match["scope"] if match else None,
            "tracking": ids,
        }
        groups["chore" if kind == "style" else kind if kind in groups else "other"].append(entry)
        if (match and match["bang"]) or "BREAKING CHANGE" in body:
            breaking.append(entry)
    release_notes = [{"kind": kind, **item} for kind in USER_FACING for item in groups[kind]]
    report = {
        "schema_version": "1.0",
        "command": "changelog",
        "draft": True,
        "approval": (
            "DRAFT. A human must check accuracy and remove sensitive detail before publishing."
        ),
        "range": {"from": start, "to": end, "commits": len(commits), "limit": MAX_COMMITS},
        "technical": {name: items for name, items in groups.items() if items},
        "breaking": breaking,
        "release_notes": release_notes,
        "hygiene": {
            "conventional": conventional,
            "not_conventional": len(loose),
            "without_tracking_id": untracked,
            "examples": loose[:10],
        },
    }
    return clean(report)


def render_markdown(report: dict) -> str:
    out = [f"> {report['approval']}", ""]
    rng = report["range"]
    out.append(f"Range: `{rng['from'] or 'start'}..{rng['to']}` ({rng['commits']} commits)")
    if report["breaking"]:
        out += ["", "## Breaking changes"]
        out += [f"- {e['subject']} ({e['sha']})" for e in report["breaking"]]
    out += ["", "## Release notes (user-facing)"]
    notes = report["release_notes"]
    out += [f"- **{n['kind']}**: {n['subject']}" for n in notes] or ["- No user-facing commits."]
    out += ["", "## Technical changelog"]
    for name, items in report["technical"].items():
        out.append(f"### {name}")
        for e in items:
            ids = f" [{', '.join(e['tracking'])}]" if e["tracking"] else ""
            scope = f"{e['scope']}: " if e["scope"] else ""
            out.append(f"- {scope}{e['subject']}{ids} ({e['sha']})")
    hygiene = report["hygiene"]
    out += ["", "## Commit hygiene"]
    out.append(
        f"- {hygiene['not_conventional']} commit(s) do not follow `type(scope): subject`; "
        f"{hygiene['without_tracking_id']} have no tracking ID."
    )
    out += [f"  - {text}" for text in hygiene["examples"]]
    return "\n".join(out)
