"""Post RADEA result JSON as a comment to GitHub PR or GitLab MR."""

from __future__ import annotations

import json
import os
import re
import urllib.parse
import urllib.request
from pathlib import Path

from radea.core.contracts import validate
from radea.core.sanitizer import clean


def _md_debug(r: dict) -> str:
    r = clean(r)
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
    r = clean(r)
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
    with Path(result_file).open("rb") as stream:
        raw = stream.read(1_048_577)
    if len(raw) > 1_048_576:
        raise ValueError("Result file exceeds 1 MiB")
    r = json.loads(raw)
    if (
        not isinstance(r, dict)
        or r.get("draft") is not True
        or r.get("evidence_verified") is not True
        or r.get("verified") is not False
        or r.get("error")
        or r.get("schema_version") != "1.0"
    ):
        raise ValueError("Only validated RADEA draft results can be posted")
    kind = r.get("command")
    validate(kind, r, r.get("evidence", {}))
    # Plain JSON in a code block prevents model-authored Markdown/HTML and mentions.
    content = json.dumps(clean(r), indent=2, ensure_ascii=False).replace(
        "```", "\u0060 \u0060 \u0060"
    )
    content = content.replace("@", "@\u200b")
    if len(content) > 50000:
        raise ValueError("Comment exceeds safe size; retain the result as a private artifact")
    body = (
        "## RADEA — AI DRAFT\n"
        "> Evidence references checked; conclusions require human review.\n\n```json\n"
        + content
        + "\n```"
    )
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
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo) or not pr_num.isdecimal():
        raise ValueError("Invalid GitHub comment target")
    url = f"https://api.github.com/repos/{repo}/issues/{pr_num}/comments"
    _http_post(
        url,
        {"body": body},
        {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
    )
    print(f"[radea] Posted comment to GitHub PR #{pr_num}")


def _github_pr_number() -> str | None:
    if os.getenv("PR_NUMBER", "").isdecimal():
        return os.environ["PR_NUMBER"]
    # workflow_run event: PR number lives in GITHUB_EVENT_PATH
    event_path = os.getenv("GITHUB_EVENT_PATH")
    if event_path:
        try:
            event = json.loads(Path(event_path).read_text())
            if event.get("pull_request", {}).get("number"):
                return str(event["pull_request"]["number"])
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
    token = os.environ["GITLAB_TOKEN"]
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
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            raise ValueError("Comment API redirects are not allowed")

    opener = urllib.request.build_opener(NoRedirect)
    with opener.open(req, timeout=30):
        pass
