"""Small immutable request types and explicit extension ports."""

from dataclasses import dataclass
from typing import Any, Literal, Protocol

from radea.core.config import Config

Command = Literal["debug", "iac-review", "triage"]
Result = dict[str, Any]


@dataclass(frozen=True)
class AnalysisRequest:
    """An analysis request contains intent and paths, never API credentials."""

    command: Command
    paths: tuple[str, ...] = ()
    plan_file: str | None = None
    metrics_file: str | None = None
    baseline: str = "7d"
    local: bool = False
    dry_run: bool = False
    sanitize_input: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "paths", tuple(str(path) for path in self.paths))
        if self.command not in {"debug", "iac-review", "triage"}:
            raise ValueError("Unknown analysis command")
        if self.command != "iac-review" and self.plan_file:
            raise ValueError("plan_file is only supported for iac-review")
        if self.command != "triage" and self.metrics_file:
            raise ValueError("metrics_file is only supported for triage")
        if not self.paths and not self.plan_file:
            raise ValueError("At least one source or plan is required")


class ModelClient(Protocol):
    """Implement this callable to integrate an approved inference transport."""

    def __call__(self, *, system: str, user: str, cfg: Config) -> Result: ...
