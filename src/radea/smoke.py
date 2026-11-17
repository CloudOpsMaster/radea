"""An explicit, single-request synthetic live inference acceptance check."""

import tempfile
import time
from pathlib import Path

from radea.api import AnalysisRequest, Config, analyze
from radea.core.diagnostics import readiness
from radea.core.provider_errors import public_details


def probe(config: Config) -> dict:
    status = readiness(config)
    if not status["configured"]:
        return {
            **status,
            "mode": "live_smoke",
            "status": "unavailable",
            "inference_attempted": False,
        }
    with tempfile.TemporaryDirectory(prefix="radea-smoke-") as directory:
        path = Path(directory) / "synthetic.log"
        path.write_text("ERROR acceptance fixture: ModuleNotFoundError: acme_demo\n")
        started = time.monotonic()
        result = analyze(AnalysisRequest(command="debug", paths=(str(path),)), config=config)
    passed = not result.get("error") and result.get("evidence_verified") is True
    return {
        "mode": "live_smoke",
        "status": "passed" if passed else "failed",
        "provider": status["provider"],
        "model": status["model"],
        "inference_attempted": True,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "contract_valid": passed,
        "draft": True,
        "verified": False,
        "error": result.get("error"),
        **public_details(result),
        "limitations": [
            "Synthetic transport/contract check; not diagnostic accuracy certification."
        ],
    }
