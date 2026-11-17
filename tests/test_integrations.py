"""End-to-end local contracts: GitHub API data → validated draft → comment boundary."""

import io
import json
import urllib.request
import zipfile
from unittest.mock import patch

import pytest

from radea.integrations import github
from radea.notify.comment import post_comment


def test_failed_job_to_sanitized_pr_comment(tmp_path, monkeypatch, cloud_model):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("GITHUB_TOKEN", "dummy")
    routes = []
    secret = "ghp_" + "a" * 30

    def fetch(route, **kwargs):
        routes.append(route)
        if route.endswith("/runs/12"):
            return json.dumps(
                {
                    "head_repository": {"full_name": "owner/repo"},
                    "conclusion": "failure",
                    "pull_requests": [{"number": 5}],
                }
            ).encode()
        if "jobs?" in route:
            return json.dumps(
                {"jobs": [{"id": 7, "conclusion": "failure"}], "total_count": 1}
            ).encode()
        assert route.endswith("/jobs/7/logs")
        return f"ERROR import failed token={secret}\n".encode()

    def model(**kwargs):
        payload = json.loads(kwargs["user"])
        assert secret not in kwargs["user"]
        assert "UNTRUSTED DATA" in kwargs["system"]
        ref = next(iter(payload["evidence"]))
        return {
            "category": "code_error",
            "hypotheses": [
                {
                    "title": "Import failed",
                    "description": "Investigate the import",
                    "confidence": "low",
                    "verify": "inspect requirements.txt",
                    "evidence_ids": [ref],
                }
            ],
        }

    with (
        patch.object(github, "fetch", side_effect=fetch),
        patch("radea.core.llm.call", side_effect=model),
    ):
        result = github.analyze_run("owner/repo", "12", str(tmp_path))
    target = tmp_path / "result.json"
    target.write_text(json.dumps(result))
    with patch("radea.notify.comment._http_post") as post:
        post_comment(str(target))
    assert post.call_args.args[0] == "https://api.github.com/repos/owner/repo/issues/5/comments"
    body = post.call_args.args[1]["body"]
    assert secret not in body and "AI DRAFT" in body
    assert "s1:L1" in body and result["verified"] is False
    assert all("/runs/12/logs" not in route for route in routes)


def test_untrusted_fork_skipped_before_inference(tmp_path):
    metadata = {
        "head_repository": {"full_name": "attacker/fork"},
        "conclusion": "failure",
        "pull_requests": [{"number": 5}],
    }
    with (
        patch.object(github, "fetch", return_value=json.dumps(metadata).encode()),
        patch("radea.core.llm.call") as model,
    ):
        assert github.analyze_run("owner/repo", "12", str(tmp_path)) is None
    model.assert_not_called()


def test_log_redirect_never_forwards_token():
    request = urllib.request.Request(
        "https://api.github.com/logs", headers={"Authorization": "Bearer dummy"}
    )
    redirected = github.SafeRedirect().redirect_request(
        request, None, 302, "Found", {}, "https://logs.example/signed"
    )
    assert redirected.get_header("Authorization") is None
    with pytest.raises(ValueError):
        github.SafeRedirect().redirect_request(
            request, None, 302, "Found", {}, "http://logs.example"
        )


def test_plan_artifact_is_read_as_data_and_delete_is_independent(tmp_path, cloud_model):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr(
            "plan.json",
            json.dumps(
                {
                    "format_version": "1.2",
                    "resource_changes": [
                        {"address": "aws_db_instance.prod", "change": {"actions": ["delete"]}}
                    ],
                }
            ),
        )

    def fetch(route, **kwargs):
        if route.endswith("/runs/12"):
            return json.dumps(
                {
                    "head_repository": {"full_name": "owner/repo"},
                    "conclusion": "success",
                    "pull_requests": [{"number": 5}],
                }
            ).encode()
        if "artifacts?" in route:
            return json.dumps(
                {"artifacts": [{"id": 9, "name": "terraform-plan", "expired": False}]}
            ).encode()
        assert route.endswith("/artifacts/9/zip")
        return buf.getvalue()

    with (
        patch.object(github, "fetch", side_effect=fetch),
        patch("radea.core.llm.call", return_value={"summary": "Draft", "findings": []}),
    ):
        result = github.analyze_plan_run("owner/repo", "12", str(tmp_path))
    assert result["destructive_actions"][0]["action"] == "destroy"
    assert not result.get("error")


def test_unsafe_artifact_name_rejected(tmp_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr("../plan.json", "{}")

    def fetch(route, **kwargs):
        if route.endswith("/runs/12"):
            return json.dumps(
                {
                    "head_repository": {"full_name": "owner/repo"},
                    "conclusion": "success",
                    "pull_requests": [{"number": 5}],
                }
            ).encode()
        if "artifacts?" in route:
            return json.dumps({"artifacts": [{"id": 9, "name": "terraform-plan"}]}).encode()
        return buf.getvalue()

    with patch.object(github, "fetch", side_effect=fetch), pytest.raises(ValueError, match="only"):
        github.analyze_plan_run("owner/repo", "12", str(tmp_path))


def test_unvalidated_result_cannot_be_posted(tmp_path):
    path = tmp_path / "result.json"
    path.write_text(json.dumps({"category": "unknown", "hypotheses": []}))
    with (
        patch("radea.notify.comment._http_post") as post,
        pytest.raises(ValueError, match="validated"),
    ):
        post_comment(str(path))
    post.assert_not_called()


def test_evaluation_reports_missing_and_missed_risk(tmp_path):
    from radea.evaluation import score

    cases = [
        {"id": "missing", "command": "debug", "expected_destructive_resources": []},
        {"id": "delete", "command": "iac-review", "expected_destructive_resources": ["db"]},
    ]
    (tmp_path / "delete.json").write_text(
        json.dumps(
            {
                "summary": "Draft",
                "findings": [],
                "draft": True,
                "verified": False,
                "destructive_actions": [],
            }
        )
    )
    report = score(cases, tmp_path)
    assert report["cases"][0]["status"] == "missing_response"
    assert report["cases"][1]["missed_destructive_resources"] == ["db"]


def test_empty_actions_pr_metadata_resolves_exact_sha():
    run = {"pull_requests": [], "head_branch": "feature/demo", "head_sha": "a" * 40}
    pr = {
        "number": 42,
        "state": "open",
        "head": {"sha": "a" * 40, "repo": {"full_name": "owner/repo"}},
        "base": {"repo": {"full_name": "owner/repo"}},
    }
    with patch.object(github, "fetch", return_value=json.dumps([pr]).encode()):
        assert github.pull_request_number("owner/repo", run) == 42
    pr["head"]["sha"] = "b" * 40
    with patch.object(github, "fetch", return_value=json.dumps([pr]).encode()):
        assert github.pull_request_number("owner/repo", run) is None


def test_empty_actions_pr_metadata_rejects_ambiguous_matches():
    run = {"pull_requests": [], "head_branch": "feature", "head_sha": "a" * 40}
    pr = {
        "number": 42,
        "state": "open",
        "head": {"sha": "a" * 40, "repo": {"full_name": "owner/repo"}},
        "base": {"repo": {"full_name": "owner/repo"}},
    }
    with patch.object(github, "fetch", return_value=json.dumps([pr, pr]).encode()):
        assert github.pull_request_number("owner/repo", run) is None
