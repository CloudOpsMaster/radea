"""Changelog drafts from a real throw-away git repository."""

import json
import subprocess

import pytest
from click.testing import CliRunner

from radea.cli import main
from radea.static_review.changelog import build, render_markdown

ENV = {
    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid",
    "PATH": "/usr/bin:/bin:/usr/local/bin", "HOME": "/tmp",
}  # fmt: skip


def git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, env=ENV)


@pytest.fixture()
def repo(tmp_path):
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "commit.gpgsign", "false")
    for number, message in enumerate(
        [
            "chore: initial",
            "feat(api): add export endpoint\n\nTracking-Id: JIRA-ID: ABC-12",
            "fix: handle empty input ABC-13",
            "perf!: drop legacy cache\n\nBREAKING CHANGE: cache API removed",
            "[no-jira][SE] automated version increase",
            "quick fix of stuff",
            "docs: explain flags",
        ]
    ):
        (tmp_path / "f.txt").write_text(str(number))
        git(tmp_path, "add", "f.txt")
        git(tmp_path, "commit", "-q", "-m", message)
        if number == 0:
            git(tmp_path, "tag", "v0")
    return tmp_path


def test_groups_commits_and_flags_breaking_changes(repo):
    report = build(str(repo), "v0", "HEAD")
    assert report["draft"] is True and report["range"]["commits"] == 6
    assert [e["subject"] for e in report["technical"]["feat"]] == ["add export endpoint"]
    assert report["technical"]["feat"][0]["tracking"] == ["ABC-12"]
    assert [e["subject"] for e in report["breaking"]] == ["drop legacy cache"]
    kinds = [n["kind"] for n in report["release_notes"]]
    assert kinds == ["feat", "fix", "perf"]  # only user-facing commits, in a fixed order
    assert "chore" in report["technical"]  # automated version increase is maintenance


def test_hygiene_report_is_honest(repo):
    hygiene = build(str(repo), "v0", "HEAD")["hygiene"]
    assert hygiene["not_conventional"] == 1 and hygiene["examples"] == ["quick fix of stuff"]
    assert hygiene["conventional"] == 4
    assert hygiene["without_tracking_id"] >= 3


def test_markdown_carries_the_approval_notice(repo):
    text = render_markdown(build(str(repo), "v0", "HEAD"))
    assert text.startswith("> DRAFT.")
    assert "## Breaking changes" in text and "## Commit hygiene" in text


@pytest.mark.parametrize("ref", ["--output=/tmp/x", "-n1", "a..b", "a b", "$(id)", ";ls"])
def test_option_like_and_malformed_refs_are_rejected(repo, ref):
    with pytest.raises(ValueError, match="Invalid"):
        build(str(repo), ref, "HEAD")


def test_unknown_ref_is_a_clean_error(repo):
    with pytest.raises(ValueError, match="git log failed"):
        build(str(repo), "no-such-tag", "HEAD")


def test_directory_that_is_not_a_repository_is_a_clean_error(tmp_path_factory):
    plain = tmp_path_factory.mktemp("plain")
    with pytest.raises(ValueError, match="git log failed"):
        build(str(plain), None, "HEAD")
    with pytest.raises(ValueError, match="not a directory"):
        build(str(plain / "missing"), None, "HEAD")


def test_secrets_in_commit_messages_are_redacted(repo):
    (repo / "f.txt").write_text("x")
    git(repo, "add", "f.txt")
    git(repo, "commit", "-q", "-m", "fix: rotate password=hunter2hunter2 in config")
    assert "hunter2hunter2" not in json.dumps(build(str(repo), "v0", "HEAD"))


def test_cli(repo):
    runner = CliRunner()
    ok = runner.invoke(main, ["changelog", "--repo", str(repo), "--from", "v0", "--output", "json"])
    assert ok.exit_code == 0 and json.loads(ok.output)["draft"] is True
    bad = runner.invoke(main, ["changelog", "--repo", str(repo), "--from", "--oops"])
    assert bad.exit_code == 1 and "Invalid from reference" in bad.output
