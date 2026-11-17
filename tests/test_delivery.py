"""Release contracts that do not depend on a live GitHub account."""

import re
from pathlib import Path


def test_actions_are_pinned_to_full_commits():
    paths = list(Path(".github/workflows").glob("*.yml")) + list(
        Path("ci/github-actions").glob("*.yml")
    )
    for path in paths:
        for ref in re.findall(r"uses:\s+([^\s#]+)", path.read_text()):
            if ref.startswith("./"):
                continue
            assert re.fullmatch(r"[\w.-]+/[\w.-]+@[0-9a-f]{40}", ref), (path, ref)


def test_release_promotes_checked_artifact_and_attests_it():
    release = Path(".github/workflows/release.yml").read_text()
    assert "needs: checks" in release and "actions/download-artifact@" in release
    assert "sha256sum --check SHA256SUMS" in release
    assert "python -m build" not in release
    assert "actions/attest-build-provenance@" in release
    ci = Path(".github/workflows/ci.yml").read_text()
    assert "runtime-dependencies.cdx.json" in ci
    assert "pip install --require-hashes -r requirements-ci.lock" in ci


def test_runtime_lock_has_no_implicit_unpinned_requirements():
    text = Path("requirements-runtime.lock").read_text()
    packages = [line for line in text.splitlines() if line and not line.startswith((" ", "#"))]
    assert packages and all("==" in line for line in packages)
    assert text.count("--hash=sha256:") >= len(packages)
