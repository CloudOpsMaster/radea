"""Evidence-based advisory analysis with shared runtime guardrails."""

from pathlib import Path

from radea.core.runtime import run_command


def compress_logs(
    *,
    logs_path: str,
    metrics_path: str | None,
    baseline: str = "7d",
    output: str = "text",
    local: bool = False,
    dry_run: bool = False,
) -> dict:
    source = Path(logs_path)
    paths = [str(p) for p in sorted(source.glob("*.log"))] if source.is_dir() else [logs_path]
    if metrics_path:
        paths.append(metrics_path)
    return run_command(
        kind="triage",
        paths=paths,
        baseline=baseline,
        metrics_file=metrics_path,
        output=output,
        local=local,
        dry_run=dry_run,
    )
