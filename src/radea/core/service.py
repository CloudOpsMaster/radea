"""Application service: prepare domain facts, then invoke the guarded runtime."""

import re
from dataclasses import replace

from radea.core.config import Config
from radea.core.models import AnalysisRequest, ModelClient, Result
from radea.core.prompts import PROMPTS
from radea.core.results import failure
from radea.core.runtime import execute
from radea.iac_review.plan import inspect_plan
from radea.incident_triage.metrics import compare


class AnalysisService:
    """A reusable service with explicit configuration and model dependencies."""

    def __init__(self, config: Config | None = None, model: ModelClient | None = None):
        self._config = config
        self._model = model

    def analyze(self, request: AnalysisRequest) -> Result:
        facts = metrics = None
        try:
            configured = self._config if self._config is not None else Config.from_env()
            cfg = replace(configured, local=configured.local or request.local)
            if not request.sanitize_input:
                raise ValueError("Sanitization cannot be disabled")
            system = PROMPTS[request.command]
            paths = list(request.paths)
            if request.command == "triage":
                if not re.fullmatch(r"[1-9][0-9]{0,3}[hdw]", request.baseline):
                    raise ValueError("Invalid baseline window")
                system += (
                    f"\nRequested baseline: {request.baseline}. "
                    "Metrics are user-provided; no historical data is fetched.\n"
                )
            if request.metrics_file:
                metrics = compare(request.metrics_file, request.baseline, cfg.max_input_bytes)
                if request.metrics_file not in paths:
                    paths.append(request.metrics_file)
            if request.plan_file:
                facts = inspect_plan(request.plan_file, cfg.max_input_bytes)
            result = execute(
                kind=request.command,
                system=system,
                paths=paths,
                cfg=cfg,
                dry_run=request.dry_run,
                facts=facts,
                metrics=metrics,
                model_client=self._model,
            )
            if request.command == "iac-review" and not request.plan_file:
                result["plan_status"] = "not_provided"
                result.setdefault("warnings", []).append(
                    "No plan supplied; destruction was not assessed."
                )
            if request.command == "triage":
                result["baseline_status"] = (
                    "computed_from_supplied_values" if metrics is not None else "not_provided"
                )
            return result
        except (OSError, ValueError):
            result = failure(
                request.command, "Invalid input or configuration; no analysis completed"
            )
            if request.command == "iac-review":
                result["plan_status"] = "invalid_or_unreadable"
            return result
