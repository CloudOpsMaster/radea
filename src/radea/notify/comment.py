"""Post RADEA result JSON as a comment to GitHub PR or GitLab MR."""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from pathlib import Path


def _md_debug(r: dict) -> str:
    rows = "\n".join(
        f"| {i} | **{h['title']}** | {h['confidence']} | {h['description']} | `{h['verify']}` |"
        for i, h in enumerate(r.get("hypotheses", []), 1)
    )
    redactions = r.get("sanitizer", {}).get("redactions", 0)
    return "\n".join(
        [
            "## RADEA Build Triage — AI DRAFT",
            "> Verify every item before acting.",
            "",
            f"**Failure type:** `{r.get('category', 'unknown')}`",
            "",
            "| # | Cause | Confidence | Description | Verify |",
            "|---|-------|-----------|-------------|--------|",
            rows,
            "",
            f"*Sanitizer: {redactions} redaction(s) applied.*",
        ]
    )


def _md_iac(r: dict) -> str:
    lines = [
        "## RADEA IaC Review — AI DRAFT",
        "> Review every finding. Never merge on AI output alone.",
        "",
    ]
    if r.get("destructive_actions"):
        lines += ["### ⛔ STOP — Destructive actions detected", ""]
        for a in r["destructive_actions"]:
            lines.append(f"- **{a['resource']}** → `{a['action']}`")
        lines.append("")

    if r.get("findings"):
        _sev = {"high": "🔴", "medium": "🟡", "low": "🟢", "info": "ℹ️"}
        lines += [
            "### Findings",
            "",
            "| | Finding | Resource | Description |",
            "|---|---------|----------|-------------|",
        ]
        for f in r["findings"]:
            lines.append(
                f"| {_sev.get(f['severity'], 'ℹ️')} | **{f['title']}** | "
                f"`{f['resource']}` | {f['description']} |"
            )
        lines.append("")

    if r.get("summary"):
        lines += ["### What this code provisions", r["summary"]]

    return "\n".join(lines)


def post_comment(result_file: str) -> None:
    """Detect CI environment, build Markdown body, post to PR/MR."""
    r = json.loads(Path(result_file).read_text())
    kind = "iac" if "findings" in r else "debug"
    body = _md_iac(r) if kind == "iac" else _md_debug(r)

    if os.getenv("GITHUB_ACTIONS"):
        _post_github(body)
    elif os.getenv("GITLAB_CI"):
        _post_gitlab(body)
    else:
        print(body)


# ── GitHub ────────────────────────────────────────────────────────────────────


def _post_github(body: str) -> None:
    token = os.environ["GITHUB_TOKEN"]
    repo = os.environ["GITHUB_REPOSITORY"]
    pr_num = _github_pr_number()
    if not pr_num:
        print("[radea] Not a PR run — printing comment body:\n")
        print(body)
        return
    url = f"https://api.github.com/repos/{repo}/issues/{pr_num}/comments"
    _http_post(
        url,
        {"body": body},
        {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
    )
    print(f"[radea] Posted comment to GitHub PR #{pr_num}")


def _github_pr_number() -> str | None:
    # workflow_run event: PR number lives in GITHUB_EVENT_PATH
    event_path = os.getenv("GITHUB_EVENT_PATH")
    if event_path:
        try:
            event = json.loads(Path(event_path).read_text())
            prs = event.get("workflow_run", {}).get("pull_requests", [])
            if prs:
                return str(prs[0]["number"])
        except Exception:  # noqa: BLE001
            pass
    # pull_request event
    return os.getenv("PR_NUMBER")


# ── GitLab ────────────────────────────────────────────────────────────────────


def _post_gitlab(body: str) -> None:
    mr_iid = os.getenv("CI_MERGE_REQUEST_IID")
    if not mr_iid:
        print("[radea] Not a MR pipeline — printing comment body:\n")
        print(body)
        return
    api = os.environ["CI_API_V4_URL"]
    project = os.environ["CI_PROJECT_ID"]
    token = os.environ["CI_JOB_TOKEN"]
    url = f"{api}/projects/{project}/merge_requests/{mr_iid}/notes"
    _http_post(url, {"body": body}, {"PRIVATE-TOKEN": token})
    print(f"[radea] Posted note to GitLab MR !{mr_iid}")


# ── Shared ────────────────────────────────────────────────────────────────────


def _http_post(url: str, payload: dict, headers: dict) -> None:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Comment API URL must use HTTPS without embedded credentials")
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    for k, v in headers.items():
        req.add_header(k, v)
    # The scheme is restricted to HTTPS above; urllib rejects file redirects.
    with urllib.request.urlopen(req, timeout=30):  # nosec B310
        pass
