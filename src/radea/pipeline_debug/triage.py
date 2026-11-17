"""Evidence-based advisory analysis with shared runtime guardrails."""

from radea.core.runtime import run_command


def triage_log(
    *,
    log_path: str,
    sanitize_input: bool = True,
    output: str = "text",
    local: bool = False,
    dry_run: bool = False,
) -> dict:
    return run_command(
        kind="debug",
        paths=[log_path],
        sanitize_input=sanitize_input,
        output=output,
        local=local,
        dry_run=dry_run,
    )
