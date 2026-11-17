"""Opt-in real GitHub log/comment acceptance with explicitly fixture-only inference."""

import argparse
import json
import os
import tempfile
from pathlib import Path

from radea.api import AnalysisService, Config
from radea.integrations.github import analyze_run
from radea.notify.comment import post_comment


def fixture_model(*, system: str, user: str, cfg: Config) -> dict:
    """Deterministic acceptance data, never a model quality claim."""
    payload = json.loads(user)
    matches = [
        ref
        for ref, line in payload["evidence"].items()
        if "RADEA_ACCEPTANCE_INTENTIONAL_FAILURE" in line
    ]
    if not matches:
        raise ValueError("Controlled failure marker was not collected")
    return {
        "category": "code_error",
        "hypotheses": [
            {
                "title": "ACCEPTANCE FIXTURE: controlled test failure",
                "confidence": "high",
                "description": "The acceptance failure marker appears in the real job logs.",
                "verify": "Inspect tests/test_controlled_acceptance_failure.py in the fixture PR",
                "evidence_ids": matches[:1],
            }
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live-github", action="store_true", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--pr", required=True, type=int)
    parser.add_argument("--post-fixture-comment", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="radea-github-live-") as directory:
        service = AnalysisService(Config(audit_dir=str(Path(directory) / "audit")), fixture_model)
        result = analyze_run(args.repository, args.run_id, directory, service=service)
        if result is None or result.get("error"):
            raise RuntimeError("Real GitHub transport did not produce a validated fixture")
        if os.environ.get("PR_NUMBER") != str(args.pr):
            raise RuntimeError("Resolved PR does not match explicit target")
        result["warnings"].append(
            "ACCEPTANCE FIXTURE: real GitHub transport; "
            "deterministic test model, no live inference."
        )
        result_path = Path(directory) / "result.json"
        result_path.write_text(json.dumps(result))
        if args.post_fixture_comment:
            os.environ["GITHUB_ACTIONS"] = "true"
            os.environ["GITHUB_REPOSITORY"] = args.repository
            post_comment(str(result_path))
        report = {
            "repository": args.repository,
            "run_id": args.run_id,
            "pull_request": args.pr,
            "github_transport": "live",
            "inference": "deterministic_fixture_only",
            "comment_posted": args.post_fixture_comment,
            "evidence_verified": result["evidence_verified"],
            "failed_jobs_collected": len(result["sources"]),
            "transport": result["provenance"]["transport"],
            "input_sha256": result["provenance"]["input_sha256"],
        }
        args.output.write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
