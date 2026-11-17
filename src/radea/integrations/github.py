"""Trusted workflow_run adapter: fetch failed job text, analyze, post a draft."""

import io
import json
import os
import re
import tempfile
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

from radea.api import AnalysisRequest, analyze


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urllib.parse.urlsplit(newurl).scheme != "https":
            raise ValueError("Only HTTPS log redirects are permitted")
        # Log downloads use signed URLs. Never forward the GitHub credential.
        return urllib.request.Request(newurl, headers={"Accept": "application/octet-stream"})


def fetch(route: str, *, limit: int) -> bytes:
    request = urllib.request.Request(
        "https://api.github.com/" + route,
        headers={
            "Authorization": "Bearer " + os.environ["GITHUB_TOKEN"],
            "Accept": "application/vnd.github+json",
            "User-Agent": "radea",
        },
    )
    opener = urllib.request.build_opener(SafeRedirect)
    with opener.open(request, timeout=30) as response:
        body = response.read(limit + 1)
    if len(body) > limit:
        raise ValueError("GitHub response exceeds collection limit")
    return body


def analyze_run(repository: str, run_id: str, directory: str) -> dict | None:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository) or not run_id.isdecimal():
        raise ValueError("Invalid repository or run ID")
    run = json.loads(fetch(f"repos/{repository}/actions/runs/{run_id}", limit=1_048_576))
    # Never spend privileged workflow credentials on an untrusted fork run.
    if run.get("head_repository", {}).get("full_name") != repository:
        return None
    if run.get("conclusion") != "failure":
        return None
    pull_requests = run.get("pull_requests", [])
    if len(pull_requests) != 1 or type(pull_requests[0].get("number")) is not int:
        return None
    listing = json.loads(
        fetch(f"repos/{repository}/actions/runs/{run_id}/jobs?per_page=100", limit=1_048_576)
    )
    failed = [job for job in listing.get("jobs", []) if job.get("conclusion") == "failure"]
    if not failed:
        raise ValueError("No failed job logs available")
    paths = []
    for job in failed[:4]:
        if type(job.get("id")) is not int:
            raise ValueError("Invalid job ID")
        body = fetch(f"repos/{repository}/actions/jobs/{job['id']}/logs", limit=1_048_576)
        if body.startswith(b"PK\x03\x04"):
            raise ValueError("Expected job text logs, received an archive")
        path = Path(directory) / f"job-{job['id']}.log"
        path.write_bytes(body)
        paths.append(str(path))
    result = analyze(AnalysisRequest(command="debug", paths=tuple(paths)))
    if len(failed) > 4 or listing.get("total_count", 0) > len(listing.get("jobs", [])):
        result.setdefault("warnings", []).append(
            "Only the first four failed jobs on the first API page were collected."
        )
        result.setdefault("provenance", {})["incomplete"] = True
    os.environ["PR_NUMBER"] = str(pull_requests[0]["number"])
    return result


def analyze_plan_run(repository: str, run_id: str, directory: str) -> dict | None:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository) or not run_id.isdecimal():
        raise ValueError("Invalid repository or run ID")
    run = json.loads(fetch(f"repos/{repository}/actions/runs/{run_id}", limit=1_048_576))
    if (
        run.get("head_repository", {}).get("full_name") != repository
        or run.get("conclusion") != "success"
        or len(run.get("pull_requests", [])) != 1
    ):
        return None
    pr = run["pull_requests"][0].get("number")
    if type(pr) is not int or pr < 1:
        raise ValueError("Invalid PR number")
    listing = json.loads(
        fetch(f"repos/{repository}/actions/runs/{run_id}/artifacts?per_page=100", limit=1_048_576)
    )
    artifacts = [
        a
        for a in listing.get("artifacts", [])
        if a.get("name") == "terraform-plan" and not a.get("expired")
    ]
    if len(artifacts) != 1 or type(artifacts[0].get("id")) is not int:
        raise ValueError("Exactly one terraform-plan artifact is required")
    maximum = 8 * 1024 * 1024
    raw = fetch(f"repos/{repository}/actions/artifacts/{artifacts[0]['id']}/zip", limit=maximum)
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        names = archive.namelist()
        if names != ["plan.json"] or archive.getinfo("plan.json").file_size > maximum:
            raise ValueError("Artifact must contain only a bounded plan.json")
        with archive.open("plan.json") as entry:
            data = entry.read(maximum + 1)
        if len(data) > maximum:
            raise ValueError("Plan exceeds size limit")
    path = Path(directory) / "plan.json"
    path.write_bytes(data)
    result = analyze(AnalysisRequest(command="iac-review", plan_file=str(path)))
    os.environ["PR_NUMBER"] = str(pr)
    return result


def main() -> int:
    try:
        with tempfile.TemporaryDirectory(prefix="radea-workflow-") as directory:
            analyze = (
                analyze_plan_run
                if os.getenv("RADEA_WORKFLOW_MODE") == "iac-review"
                else analyze_run
            )
            result = analyze(os.environ["GITHUB_REPOSITORY"], os.environ["RADEA_RUN_ID"], directory)
            if result is None:
                print("Skipped: no single trusted same-repository PR failure.")
                return 0
            if result.get("error"):
                print("Analysis failed validation; no PR comment posted.")
                return 1
            from radea.notify.comment import post_comment

            path = Path(directory) / "result.json"
            path.write_text(json.dumps(result))
            post_comment(str(path))
        return 0
    except Exception:
        print("GitHub triage failed; no unverified result was published.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
