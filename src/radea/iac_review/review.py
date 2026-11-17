"""Evidence-based advisory analysis with shared runtime guardrails."""

from radea.core.runtime import run_command


def review_iac(
    *,
    tf_file: str | None,
    plan_file: str | None,
    context_file: str | None,
    output: str = "text",
    local: bool = False,
    dry_run: bool = False,
) -> dict:
    return run_command(
        kind="iac-review",
        paths=[p for p in [tf_file, context_file] if p],
        plan_file=plan_file,
        output=output,
        local=local,
        dry_run=dry_run,
    )
