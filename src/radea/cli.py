"""RADEA CLI entry point."""

import click

from radea import __version__


@click.group()
@click.version_option(__version__, prog_name="radea")
def main() -> None:
    """RADEA — Reliable AI-Driven Engineering Automation.

    AI drafts. You decide. Every time.
    """


@main.command()
@click.option("--log", required=True, type=click.Path(exists=True), help="CI log file.")
@click.option(
    "--sanitize/--no-sanitize",
    default=True,
    show_default=True,
    help="Strip secrets before sending.",
)
@click.option("--output", type=click.Choice(["text", "json"]), default="text", show_default=True)
@click.option("--local", is_flag=True, help="Use local Ollama model.")
@click.option("--dry-run", is_flag=True, help="Sanitize and print the payload; skip the LLM call.")
def debug(log: str, sanitize: bool, output: str, local: bool, dry_run: bool) -> None:
    """Triage a failing CI/CD build log.

    Classifies the failure type and returns ranked probable causes,
    each with a concrete verification step. All output is AI DRAFT.
    """
    from radea.pipeline_debug.triage import triage_log

    result = triage_log(
        log_path=log, sanitize_input=sanitize, output=output, local=local, dry_run=dry_run
    )

    if result and result.get("error"):
        raise click.exceptions.Exit(1)


@main.command("iac-review")
@click.option("--file", "tf_file", type=click.Path(exists=True), help="Terraform file.")
@click.option("--plan", type=click.Path(exists=True), help="terraform plan JSON.")
@click.option("--context", type=click.Path(exists=True), help="Team conventions file.")
@click.option("--output", type=click.Choice(["text", "json"]), default="text", show_default=True)
@click.option("--local", is_flag=True, help="Use local Ollama model.")
@click.option("--dry-run", is_flag=True, help="Sanitize and print the payload; skip the LLM call.")
def iac_review(
    tf_file: str | None,
    plan: str | None,
    context: str | None,
    output: str,
    local: bool,
    dry_run: bool,
) -> None:
    """Review a Terraform file or plan.

    Flags over-permissive IAM and raises a warning on destroy/replace.
    """
    if not tf_file and not plan:
        raise click.UsageError("Provide --file or --plan (or both).")
    from radea.iac_review.review import review_iac

    result = review_iac(
        tf_file=tf_file,
        plan_file=plan,
        context_file=context,
        output=output,
        local=local,
        dry_run=dry_run,
    )

    if result and result.get("error"):
        raise click.exceptions.Exit(1)


@main.command()
@click.option("--logs", required=True, type=click.Path(exists=True), help="Log file or directory.")
@click.option("--metrics", type=click.Path(exists=True), help="Metrics JSON.")
@click.option("--baseline", default="7d", show_default=True, help="Baseline window (e.g. 7d, 24h).")
@click.option("--output", type=click.Choice(["text", "json"]), default="text", show_default=True)
@click.option("--local", is_flag=True, help="Use local Ollama model.")
@click.option("--dry-run", is_flag=True, help="Sanitize and print the payload; skip the LLM call.")
def triage(
    logs: str, metrics: str | None, baseline: str, output: str, local: bool, dry_run: bool
) -> None:
    """Compress incident logs into actionable insights.

    Clusters log lines into patterns, correlates anomalies against a
    baseline, and generates a first-draft postmortem timeline.
    """
    from radea.incident_triage.compress import compress_logs

    result = compress_logs(
        logs_path=logs,
        metrics_path=metrics,
        baseline=baseline,
        output=output,
        local=local,
        dry_run=dry_run,
    )

    if result and result.get("error"):
        raise click.exceptions.Exit(1)


@main.command("post-comment")
@click.argument("result_file", type=click.Path(exists=True))
def post_comment(result_file: str) -> None:
    """Post a RADEA result JSON as a PR/MR comment.

    Auto-detects GitHub Actions or GitLab CI from environment variables.
    Falls back to printing the Markdown body when not running in CI.

    Required env vars:
      GitHub: GITHUB_TOKEN, GITHUB_REPOSITORY
      GitLab: CI_JOB_TOKEN, CI_API_V4_URL, CI_PROJECT_ID
    """
    from radea.notify.comment import post_comment as _post

    _post(result_file)
