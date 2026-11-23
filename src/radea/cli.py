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

    Summarizes supplied evidence into patterns and a draft timeline.
    Root causes remain hypotheses; historical baselines are not fetched.
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
      GitLab: GITLAB_TOKEN, CI_API_V4_URL, CI_PROJECT_ID
    """
    from radea.notify.comment import post_comment as _post

    try:
        _post(result_file)
    except Exception:
        raise click.ClickException(
            "Comment was not posted; check validated result and API credentials"
        ) from None


@main.command("policy-check")
@click.option("--plan", required=True, type=click.Path(exists=True, dir_okay=False))
@click.option(
    "--allow-destruction", is_flag=True, help="Explicit human exception for delete/replace."
)
def policy_check(plan: str, allow_destruction: bool) -> None:
    """Deterministic plan gate. Exit 2 means policy denied; no model is called."""
    import json

    from radea.core.config import Config
    from radea.core.sanitizer import clean
    from radea.iac_review.plan import inspect_plan
    from radea.iac_review.policy import destruction_policy

    try:
        facts = inspect_plan(plan, Config.from_env().max_input_bytes)
        result = destruction_policy(facts, allow_destruction)
    except (ValueError, OSError):
        raise click.ClickException(
            "Invalid plan or configuration; policy did not allow the change"
        ) from None
    print(json.dumps(clean(result), indent=2))
    if result["decision"] == "deny":
        raise click.exceptions.Exit(2)


def _static_options(function):
    """Options shared by every deterministic review command."""
    function = click.option(
        "--fail-on",
        type=click.Choice(["high", "medium", "low", "never"]),
        default="high",
        show_default=True,
        help="Exit 2 when a finding at or above this severity exists.",
    )(function)
    return click.option(
        "--output", type=click.Choice(["text", "json"]), default="text", show_default=True
    )(function)


def _finish(build, output: str, fail_on: str) -> None:
    """Run a review, print it and apply the exit-code contract (0 clean, 2 findings, 1 error)."""
    import json

    from radea.static_review.findings import exit_code, render_text

    try:
        report = build()
    except (ValueError, OSError) as error:
        raise click.ClickException(str(error) or "Review failed") from None
    if not report["summary"]["files"]:
        reasons = "; ".join(f"{i['path']}: {i['reason']}" for i in report["skipped"][:3])
        raise click.ClickException("Nothing to review" + (f" ({reasons})" if reasons else ""))
    click.echo(json.dumps(report, indent=2) if output == "json" else render_text(report))
    code = exit_code(report, fail_on)
    if code:
        raise click.exceptions.Exit(code)


@main.command("k8s-review")
@click.argument("paths", nargs=-1, required=True, type=click.Path(allow_dash=True))
@_static_options
def k8s_review(paths: tuple[str, ...], output: str, fail_on: str) -> None:
    """Review rendered Kubernetes manifests and Helm chart sources (no cluster, no model).

    PATHS are files, directories or `-` for stdin. Render templates first:
    helm template ./chart | radea k8s-review -
    """
    from radea.core.config import Config
    from radea.static_review.runner import run_k8s

    limit = Config.from_env().max_input_bytes
    _finish(lambda: run_k8s(paths, limit), output, fail_on)


@main.command("dockerfile-review")
@click.argument("paths", nargs=-1, required=True, type=click.Path(allow_dash=True))
@_static_options
def dockerfile_review(paths: tuple[str, ...], output: str, fail_on: str) -> None:
    """Review Dockerfiles for root users, mutable tags, baked-in secrets and build hygiene.

    PATHS are Dockerfiles, directories (Dockerfile, Dockerfile.*, *.dockerfile) or `-`.
    """
    from radea.core.config import Config
    from radea.static_review.runner import run_dockerfile

    limit = Config.from_env().max_input_bytes
    _finish(lambda: run_dockerfile(paths, limit), output, fail_on)


@main.command("ci-review")
@click.argument("paths", nargs=-1, required=True, type=click.Path(allow_dash=True))
@_static_options
def ci_review(paths: tuple[str, ...], output: str, fail_on: str) -> None:
    """Review GitHub Actions workflows and GitLab CI files for supply-chain and secret risks.

    PATHS are files, directories (e.g. .github/workflows) or `-` for stdin.
    """
    from radea.core.config import Config
    from radea.static_review.runner import run_ci

    limit = Config.from_env().max_input_bytes
    _finish(lambda: run_ci(paths, limit), output, fail_on)


@main.command("vuln-triage")
@click.argument("reports", nargs=-1, required=True, type=click.Path(allow_dash=True))
@click.option(
    "--min-severity",
    type=click.Choice(["critical", "high", "medium", "low", "negligible", "unknown"]),
    default="medium",
    show_default=True,
    help="Hide findings below this scanner severity (counted, never dropped silently).",
)
@_static_options
def vuln_triage(reports: tuple[str, ...], min_severity: str, output: str, fail_on: str) -> None:
    """Group and rank Grype or Trivy JSON reports by package, fix availability and severity."""
    from radea.core.config import Config
    from radea.static_review.runner import run_vuln

    limit = Config.from_env().max_input_bytes
    _finish(lambda: run_vuln(reports, limit, min_severity), output, fail_on)


@main.command("flaky")
@click.argument("junit", nargs=-1, required=True, type=click.Path(allow_dash=True))
@click.option("--min-runs", default=2, show_default=True, type=click.IntRange(2, 1000))
@_static_options
def flaky(junit: tuple[str, ...], min_runs: int, output: str, fail_on: str) -> None:
    """Find flaky and consistently failing tests across several JUnit XML runs."""
    from radea.core.config import Config
    from radea.static_review.runner import run_flaky

    limit = Config.from_env().max_input_bytes
    _finish(lambda: run_flaky(junit, limit, min_runs), output, fail_on)


@main.command("rules")
@click.option("--output", type=click.Choice(["text", "json"]), default="text", show_default=True)
@click.option("--prefix", default="", help="Only rules whose ID starts with this, e.g. K8S.")
def rules(output: str, prefix: str) -> None:
    """List every deterministic rule with its severity and the article it comes from."""
    import json

    from radea.static_review.catalog import CATALOG

    chosen = {k: v for k, v in CATALOG.items() if k.startswith(prefix.upper())}
    if output == "json":
        click.echo(
            json.dumps(
                [
                    {
                        "rule": k,
                        "severity": v.severity,
                        "title": v.title,
                        "why": v.why,
                        "fix": v.fix,
                        "articles": list(v.articles),
                    }
                    for k, v in chosen.items()
                ],
                indent=2,
            )
        )
        return
    for key, rule in chosen.items():
        articles = ",".join(map(str, rule.articles))
        click.echo(f"{key:8} {rule.severity:6} {rule.title}  [articles {articles}]")


@main.command()
@click.option("--output", type=click.Choice(["text", "json"]), default="text")
def doctor(output: str) -> None:
    """Inspect selected provider readiness without network calls or credential output."""
    import json

    from radea.core.config import Config
    from radea.core.diagnostics import readiness

    try:
        result = readiness(Config.from_env())
    except ValueError:
        raise click.ClickException("Invalid provider configuration") from None
    if output == "json":
        print(json.dumps(result, indent=2))
    else:
        click.echo(f"Provider: {result['provider']}; configured: {result['configured']}")
        click.echo(result["next_step"])
        click.echo("Authentication and live inference have not been verified.")
    if not result["configured"]:
        raise click.exceptions.Exit(1)


@main.command("smoke")
@click.option(
    "--live",
    is_flag=True,
    required=True,
    help="Allow one synthetic inference request; provider charges may apply.",
)
@click.option("--output", type=click.Choice(["text", "json"]), default="text")
def smoke(live: bool, output: str) -> None:
    """Explicitly verify the selected authenticated backend with one synthetic request."""
    import json

    from radea.core.config import Config
    from radea.smoke import probe

    try:
        result = probe(Config.from_env())
    except ValueError:
        raise click.ClickException("Invalid provider configuration") from None
    click.echo(
        json.dumps(result, indent=2) if output == "json" else f"Live smoke: {result['status']}"
    )
    if result["status"] != "passed":
        raise click.exceptions.Exit(1)
