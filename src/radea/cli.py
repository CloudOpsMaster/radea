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


@main.command("helm-review")
@click.argument("chart", type=click.Path(exists=True, file_okay=False))
@click.option("--values", multiple=True, help="Local override file, repeat in layer order.")
@_static_options
def helm_review(chart: str, values: tuple[str, ...], output: str, fail_on: str) -> None:
    """Lint and render a local Helm chart, then review its source and manifests."""
    from radea.core.config import Config
    from radea.static_review.helm_matrix import review

    _finish(lambda: review(chart, values, Config.from_env().max_input_bytes), output, fail_on)


@main.command("helm-kustomize-diff")
@click.argument("chart", type=click.Path(exists=True, file_okay=False))
@click.argument("overlay", type=click.Path(exists=True, file_okay=False))
@click.option("--values", multiple=True, help="Local Helm override file, repeat in layer order.")
@click.option("--fail-on-change", is_flag=True)
def helm_kustomize_diff(
    chart: str, overlay: str, values: tuple[str, ...], fail_on_change: bool
) -> None:
    """Build a trusted chart and Kustomize overlay and compare their manifests."""
    import json

    from radea.core.config import Config
    from radea.static_review.helm_matrix import compare_kustomize

    try:
        report = compare_kustomize(chart, overlay, values, Config.from_env().max_input_bytes)
    except (OSError, ValueError) as error:
        raise click.ClickException(str(error)) from None
    click.echo(json.dumps(report, indent=2))
    if fail_on_change and report["changes"]:
        raise click.exceptions.Exit(2)


@main.command("helm-matrix")
@click.argument("before", type=click.Path(exists=True, file_okay=False))
@click.argument("after", type=click.Path(exists=True, file_okay=False))
@click.option("--values", multiple=True, help="Shared ENV=FILE override, repeat in layer order.")
@click.option("--before-values", multiple=True, help="ENV=FILE applied only to the baseline.")
@click.option("--after-values", multiple=True, help="ENV=FILE applied only to the candidate.")
@click.option("--fail-on-change", is_flag=True)
def helm_matrix(
    before: str, after: str, values: tuple[str, ...], fail_on_change: bool,
    before_values: tuple[str, ...], after_values: tuple[str, ...],
) -> None:
    """Compare local Helm renders across multiple values sets."""
    import json
    import subprocess

    from radea.core.config import Config
    from radea.static_review.helm_matrix import matrix

    try:
        report = matrix(
            before, after, values, Config.from_env().max_input_bytes,
            before_overrides=before_values, after_overrides=after_values,
        )
    except (ValueError, OSError, subprocess.TimeoutExpired) as error:
        raise click.ClickException(str(error)) from None
    click.echo(json.dumps(report, indent=2))
    if fail_on_change and any(item["changes"] for item in report["environments"]):
        raise click.exceptions.Exit(2)


@main.command("image-verify")
@click.argument("manifest", type=click.Path(exists=True, dir_okay=False))
@click.argument("payload", type=click.Path(exists=True, dir_okay=False))
@click.argument("signature", type=click.Path(exists=True, dir_okay=False))
@click.option("--key", type=click.Path(exists=True, dir_okay=False), required=True)
@click.option("--repository", required=True)
@click.option("--admission-namespace", help="Emit the admission allowlist ConfigMap on success.")
def image_verify(
    manifest: str, payload: str, signature: str, key: str, repository: str,
    admission_namespace: str | None,
) -> None:
    """Verify a detached image signature and its repository and digest claims."""
    import json
    import subprocess

    from radea.core.config import Config
    from radea.static_review.image_signature import admission_config, verify

    try:
        report = verify(manifest, payload, signature, key, repository,
                        Config.from_env().max_input_bytes)
        output = (
            admission_config(report, admission_namespace)
            if admission_namespace is not None and report["verified"] else report
        )
    except (ValueError, OSError, subprocess.TimeoutExpired) as error:
        raise click.ClickException(str(error)) from None
    if admission_namespace is None or report["verified"]:
        click.echo(json.dumps(output, indent=2))
    else:
        click.echo(json.dumps(report, indent=2), err=True)
    if not report["verified"]:
        raise click.exceptions.Exit(2)


@main.command("manifest-diff")
@click.argument("before", type=click.Path(dir_okay=False, allow_dash=True))
@click.argument("after", type=click.Path(dir_okay=False, allow_dash=True))
@click.option("--output", type=click.Choice(["text", "json"]), default="text")
@click.option("--fail-on-change", is_flag=True, help="Exit 2 when any resource changes.")
def manifest_diff(before: str, after: str, output: str, fail_on_change: bool) -> None:
    """Compare two rendered Kubernetes YAML streams without exposing field values."""
    import json

    from radea.core.config import Config
    from radea.static_review.manifest_diff import compare

    try:
        report = compare(before, after, Config.from_env().max_input_bytes)
    except (ValueError, OSError) as error:
        raise click.ClickException(str(error)) from None
    changes = report["changes"]
    if output == "json":
        click.echo(json.dumps(report, indent=2))
    else:
        click.echo(f"RADEA manifest-diff: {len(changes)} changed resource(s)")
        for change in changes:
            fields = ", ".join(change["fields"])
            group = change["group"] or "core"
            namespace = change["namespace"] or "<omitted>"
            target = f"{group}/{change['kind']} {namespace}/{change['name']}"
            click.echo(f"{change['action']:8} {target}" + (f" ({fields})" if fields else ""))
    if fail_on_change and changes:
        raise click.exceptions.Exit(2)


@main.command("k8s-drift")
@click.argument("desired", type=click.Path(dir_okay=False, allow_dash=True))
@click.argument("observed", type=click.Path(dir_okay=False, allow_dash=True))
@click.option("--fail-on-drift", is_flag=True, help="Exit 2 when any drift is found.")
def k8s_drift(desired: str, observed: str, fail_on_drift: bool) -> None:
    """Compare declared Kubernetes fields against a captured snapshot, offline."""
    import json

    from radea.core.config import Config
    from radea.static_review.manifest_diff import compare

    try:
        report = compare(desired, observed, Config.from_env().max_input_bytes, drift=True)
    except (ValueError, OSError) as error:
        raise click.ClickException(str(error)) from None
    click.echo(json.dumps(report, indent=2))
    if fail_on_drift and report["changes"]:
        raise click.exceptions.Exit(2)


@main.command("rbac-access")
@click.argument("snapshot", type=click.Path(dir_okay=False, allow_dash=True))
@click.option("--user", required=True)
@click.option("--group", "groups", multiple=True)
@click.option("--verb", required=True)
@click.option("--resource", required=True)
@click.option("--api-group", default="")
@click.option("--namespace", default="", help="Omit for cluster-wide resource requests.")
@click.option("--resource-name")
def rbac_access(
    snapshot: str, user: str, groups: tuple[str, ...], verb: str, resource: str, api_group: str,
    namespace: str, resource_name: str | None,
) -> None:
    """Evaluate a Kubernetes resource request against local RBAC objects."""
    import json

    from radea.core.config import Config
    from radea.static_review.rbac_access import Request, evaluate

    request = Request(user, groups, verb, resource, api_group, namespace, resource_name)
    try:
        report = evaluate(snapshot, request, Config.from_env().max_input_bytes)
    except (ValueError, OSError) as error:
        raise click.ClickException(str(error)) from None
    click.echo(json.dumps(report, indent=2))


@main.group("preview-env")
@click.option("--project", required=True)
@click.option("--pr", type=click.IntRange(1, 2**31 - 1), required=True)
@click.option("--kubeconfig", type=click.Path(exists=True, dir_okay=False), required=True)
@click.option("--context", required=True)
@click.pass_context
def preview_env(
    ctx: click.Context, project: str, pr: int, kubeconfig: str, context: str
) -> None:
    """Manage a PR-scoped Kubernetes preview with an explicit context."""
    ctx.obj = (project, pr, kubeconfig, context)


@preview_env.command("up")
@click.option("--image", required=True)
@click.option("--port", type=click.IntRange(1, 65535), default=8080, show_default=True)
@click.option("--health", default="/healthz", show_default=True)
@click.option("--command", multiple=True, help="Override container argv. Repeat per argument.")
@click.pass_obj
def preview_up(
    target: tuple[str, int, str, str], image: str, port: int, health: str, command: tuple[str, ...]
) -> None:
    """Create or update the preview and wait for readiness."""
    import json

    from radea.preview import up

    try:
        report = up(*target, image, port, health, command)
    except (ValueError, OSError) as error:
        raise click.ClickException(str(error)) from None
    click.echo(json.dumps(report, indent=2))


@preview_env.command("smoke")
@click.argument("cases", type=click.Path(exists=True, dir_okay=False))
@click.option("--port", type=click.IntRange(1, 65535), default=8080, show_default=True)
@click.pass_obj
def preview_smoke(target: tuple[str, int, str, str], cases: str, port: int) -> None:
    """Check HTTP responses from the owned preview Service."""
    import json

    from radea.core.config import Config
    from radea.preview_smoke import probe

    try:
        report = probe(*target, port, cases, Config.from_env().max_input_bytes)
    except (ValueError, OSError) as error:
        raise click.ClickException(str(error)) from None
    click.echo(json.dumps(report, indent=2))
    if not report["passed"]:
        raise click.exceptions.Exit(2)


@preview_env.command("down")
@click.pass_obj
def preview_down(target: tuple[str, int, str, str]) -> None:
    """Request deletion of the namespace owned by this preview."""
    import json

    from radea.preview import down

    try:
        report = down(*target)
    except (ValueError, OSError) as error:
        raise click.ClickException(str(error)) from None
    click.echo(json.dumps(report, indent=2))


@main.command("preview-sweep")
@click.option("--project", required=True)
@click.option("--kubeconfig", type=click.Path(exists=True, dir_okay=False), required=True)
@click.option("--context", required=True)
@click.option("--older-than-seconds", type=click.IntRange(1, 31_536_000), required=True)
@click.option("--max-deletions", type=click.IntRange(1, 100), default=25, show_default=True)
@click.option("--interval", type=click.IntRange(2, 3600), help="Repeat every N seconds.")
@click.option("--apply", is_flag=True, help="Delete expired previews after checking ownership.")
def preview_sweep(
    project: str, kubeconfig: str, context: str, older_than_seconds: int,
    max_deletions: int, apply: bool, interval: int | None,
) -> None:
    """Find or clean up expired namespaces owned by a preview project."""
    import json
    import time

    from radea.preview import sweep

    while True:
        try:
            report = sweep(project, kubeconfig, context, older_than_seconds, apply, max_deletions)
        except (ValueError, OSError) as error:
            if interval is None:
                raise click.ClickException(str(error)) from None
            click.echo(json.dumps({"error": str(error)}), err=True)
        else:
            click.echo(json.dumps(report, indent=2 if interval is None else None))
            if interval is None:
                if report["failed"]:
                    raise click.exceptions.Exit(2)
                return
        time.sleep(interval or 0)


@main.command("preview-pr")
@click.argument("event", type=click.Path(exists=True, dir_okay=False))
@click.option("--repository", required=True, help="Expected trusted GitHub OWNER/REPO.")
@click.option("--project", required=True)
@click.option("--kubeconfig", type=click.Path(exists=True, dir_okay=False), required=True)
@click.option("--context", required=True)
@click.option("--image", help="Trusted image for opening or updating a preview.")
@click.option("--port", type=click.IntRange(1, 65535), default=8080)
@click.option("--health", default="/healthz")
@click.option("--smoke", type=click.Path(exists=True, dir_okay=False),
              help="Run trusted smoke cases after opening or updating a preview.")
def preview_pr(
    event: str, repository: str, project: str, kubeconfig: str, context: str,
    image: str | None, port: int, health: str, smoke: str | None,
) -> None:
    """Reconcile a preview from same-repository GitHub pull request metadata."""
    import json

    from radea.core.config import Config
    from radea.preview import down, event_decision, up
    from radea.preview_smoke import probe
    from radea.static_review.files import collect

    report: dict
    try:
        limit = Config.from_env().max_input_bytes
        sources, _ = collect([event], max_bytes=limit)
        action, pr = event_decision(json.loads(sources[0].text), repository)
        if pr is None:
            report = {"status": "ignored"}
        elif action == "down":
            report = down(project, pr, kubeconfig, context)
        else:
            if not image:
                raise ValueError("--image is required for an open pull request preview")
            report = up(project, pr, kubeconfig, context, image, port, health, ())
            if smoke is not None:
                report["smoke"] = probe(project, pr, kubeconfig, context, port, smoke, limit)
    except (ValueError, OSError, RecursionError) as error:
        raise click.ClickException(str(error)) from None
    click.echo(json.dumps(report, indent=2))
    if "smoke" in report and not report["smoke"]["passed"]:
        raise click.exceptions.Exit(2)


@main.command("gitops-sync")
@click.option("--repo", type=click.Path(exists=True, file_okay=False), required=True)
@click.option("--ref", default="HEAD", show_default=True)
@click.option("--manifest", required=True)
@click.option("--remote", help="Fetch a branch from this configured Git remote before each sync.")
@click.option("--applyset", help="Opt in to alpha ApplySet pruning in the target namespace.")
@click.option("--kubeconfig", type=click.Path(exists=True, dir_okay=False), required=True)
@click.option("--context", required=True)
@click.option("--namespace", required=True)
@click.option("--interval", type=click.IntRange(2, 3600), help="Repeat sync every N seconds.")
@click.option("--force-conflicts", is_flag=True, help="Take ownership of conflicting fields.")
@click.option("--allow-deployments", is_flag=True, help="Also apply trusted apps/v1 Deployments.")
def gitops_sync(
    repo: str, ref: str, manifest: str, kubeconfig: str, context: str, namespace: str,
    interval: int | None, force_conflicts: bool, remote: str | None, applyset: str | None,
    allow_deployments: bool,
) -> None:
    """Reconcile a committed bundle of namespaced Kubernetes resources."""
    import json
    import time

    from radea.core.config import Config
    from radea.gitops import sync

    limit = Config.from_env().max_input_bytes
    while True:
        try:
            report = sync(
                repo, ref, manifest, kubeconfig, context, namespace, limit,
                force_conflicts=force_conflicts, remote=remote, applyset=applyset,
                allow_deployments=allow_deployments,
            )
        except (ValueError, OSError) as error:
            if interval is None:
                raise click.ClickException(str(error)) from None
            click.echo(json.dumps({"error": str(error)}), err=True)
        else:
            click.echo(json.dumps(report))
        if interval is None:
            return
        time.sleep(interval)


@main.command("k8s-workload-plan")
@click.option("--per-node", is_flag=True)
@click.option("--stable-identity", is_flag=True)
@click.option("--per-pod-storage", is_flag=True)
@click.option("--ordered", is_flag=True)
@click.option("--finite", is_flag=True)
@click.option("--scheduled", is_flag=True)
def k8s_workload_plan(
    per_node: bool, stable_identity: bool, per_pod_storage: bool, ordered: bool,
    finite: bool, scheduled: bool,
) -> None:
    """Recommend a controller for explicitly declared workload requirements."""
    import json

    from radea.static_review.workload import choose

    try:
        report = choose(per_node, stable_identity, per_pod_storage, ordered, finite, scheduled)
    except ValueError as error:
        raise click.ClickException(str(error)) from None
    click.echo(json.dumps(report, indent=2))


@main.command("crd-validate")
@click.argument("source", type=click.Path(dir_okay=False, allow_dash=True))
@click.option("--kubeconfig", type=click.Path(exists=True, dir_okay=False), required=True)
@click.option("--context", required=True)
def crd_validate(source: str, kubeconfig: str, context: str) -> None:
    """Validate one CRD with the selected API server using server-side dry-run."""
    import json

    from radea.core.config import Config
    from radea.crd_validate import validate

    try:
        report = validate(source, kubeconfig, context, Config.from_env().max_input_bytes)
    except (ValueError, OSError) as error:
        raise click.ClickException(str(error)) from None
    click.echo(json.dumps(report, indent=2))
    if not report["accepted"]:
        raise click.exceptions.Exit(2)


@main.command("k8s-capture")
@click.argument("pod")
@click.option("--kubeconfig", type=click.Path(exists=True, dir_okay=False), required=True)
@click.option("--context", required=True)
@click.option("--namespace", required=True)
@click.option("--container", help="Opt in to a bounded log excerpt for this container.")
@click.option("--previous", is_flag=True)
def k8s_capture(
    pod: str, kubeconfig: str, context: str, namespace: str, container: str | None, previous: bool
) -> None:
    """Collect Pod status, events, and optional logs using read-only kubectl calls."""
    import json

    from radea.core.config import Config
    from radea.kube_capture import capture

    try:
        report = capture(
            kubeconfig, context, namespace, pod, container, previous,
            Config.from_env().max_input_bytes,
        )
    except (ValueError, OSError, RecursionError) as error:
        raise click.ClickException(str(error)) from None
    click.echo(json.dumps(report, indent=2))


@main.command("k8s-debug-plan")
@click.argument("snapshot", type=click.Path(dir_okay=False, allow_dash=True))
@click.option("--image", required=True, help="Trusted debug image pinned by SHA-256.")
@click.option("--probe", type=click.Choice(["identity", "resolver", "interfaces"]),
              default="identity", show_default=True)
def k8s_debug_plan(snapshot: str, image: str, probe: str) -> None:
    """Prepare a restricted ephemeral-container patch for a captured Pod."""
    import json

    from radea.core.config import Config
    from radea.kube_debug_plan import plan

    try:
        patch = plan(snapshot, image, probe, Config.from_env().max_input_bytes)
    except (ValueError, OSError) as error:
        raise click.ClickException(str(error)) from None
    click.echo(json.dumps(patch, indent=2))


@main.command("k8s-smoke")
@click.argument("spec", type=click.Path(dir_okay=False, allow_dash=True))
@click.option("--kubeconfig", type=click.Path(exists=True, dir_okay=False), required=True)
@click.option("--context", required=True)
@click.option("--namespace", required=True)
@click.option("--deployment", required=True)
@click.option("--origin", required=True, help="HTTP(S) origin serving the deployed application.")
def k8s_smoke(
    spec: str, kubeconfig: str, context: str, namespace: str, deployment: str, origin: str,
) -> None:
    """Wait for Deployment rollout readiness and test HTTP responses."""
    import json

    from radea.core.config import Config
    from radea.kube_smoke import check

    try:
        report = check(
            spec, origin, kubeconfig, context, namespace, deployment,
            Config.from_env().max_input_bytes,
        )
    except (ValueError, OSError) as error:
        raise click.ClickException(str(error)) from None
    click.echo(json.dumps(report, indent=2))
    if not report["passed"]:
        raise click.exceptions.Exit(2)


@main.command("k8s-health")
@click.argument("snapshot", type=click.Path(dir_okay=False, allow_dash=True))
@click.option("--fail-on-signal", is_flag=True, help="Exit 2 when a known symptom is present.")
def k8s_health(snapshot: str, fail_on_signal: bool) -> None:
    """Summarize Pod status signals from captured kubectl JSON, offline."""
    import json

    from radea.core.config import Config
    from radea.static_review.kube_health import analyse

    try:
        report = analyse(snapshot, Config.from_env().max_input_bytes)
    except (ValueError, OSError) as error:
        raise click.ClickException(str(error)) from None
    click.echo(json.dumps(report, indent=2))
    if fail_on_signal and report["summary"]["signals"]:
        raise click.exceptions.Exit(2)


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


@main.command("shell-parity")
@click.argument("baseline", type=click.Path(exists=True, dir_okay=False))
@click.argument("candidate", type=click.Path(exists=True, dir_okay=False))
@click.argument("cases", type=click.Path(exists=True, dir_okay=False))
@click.option("--shell", type=click.Choice(["sh", "bash"]), default="sh")
@click.option("--execute", is_flag=True, help="Run both trusted local scripts.")
def shell_parity(baseline: str, candidate: str, cases: str, shell: str, execute: bool) -> None:
    """Compare exit codes, stdout and stderr for the same inputs."""
    import json

    from radea.core.config import Config
    from radea.static_review.shell_parity import compare

    if not execute:
        raise click.UsageError("Use --execute with scripts you trust")
    try:
        report = compare(
            baseline, candidate, cases, f"/bin/{shell}", Config.from_env().max_input_bytes
        )
    except (OSError, ValueError) as error:
        raise click.ClickException(str(error)) from None
    click.echo(json.dumps(report, indent=2))
    if not report["matches"]:
        raise click.exceptions.Exit(2)


@main.command("shell-graph")
@click.argument("script", type=click.Path(exists=True, dir_okay=False))
@click.option("--root", required=True, type=click.Path(exists=True, file_okay=False))
@click.option("--shell", "dialect", type=click.Choice(["bash", "posix", "mksh", "zsh"]),
              default="bash", show_default=True)
@click.option("--fail-on-partial", is_flag=True)
def shell_graph(script: str, root: str, dialect: str, fail_on_partial: bool) -> None:
    """Trace literal shell file references within a repository using shfmt."""
    import json

    from radea.core.config import Config
    from radea.static_review.shell_graph import graph

    try:
        report = graph(script, root, dialect, Config.from_env().max_input_bytes)
    except (ValueError, OSError, RuntimeError) as error:
        raise click.ClickException(str(error)) from None
    click.echo(json.dumps(report, indent=2))
    if fail_on_partial and report["partial"]:
        raise click.exceptions.Exit(2)


@main.command("shell-review")
@click.argument("script", type=click.Path(dir_okay=False, allow_dash=True))
@click.option("--baseline", type=click.Path(dir_okay=False, allow_dash=True))
@click.option("--shell", "dialect", type=click.Choice(["bash", "sh", "dash", "ksh"]))
@click.option("--fail-on-new", is_flag=True)
def shell_review(script: str, baseline: str | None, dialect: str | None, fail_on_new: bool) -> None:
    """Lint shell source with ShellCheck and optionally compare diagnostics."""
    import json
    import subprocess

    from radea.core.config import Config
    from radea.static_review.shell import review

    try:
        report = review(script, baseline, dialect, Config.from_env().max_input_bytes)
    except (ValueError, OSError, subprocess.TimeoutExpired) as error:
        raise click.ClickException(str(error)) from None
    click.echo(json.dumps(report, indent=2))
    if fail_on_new and report["introduced"]:
        raise click.exceptions.Exit(2)


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


@main.command("ci-graph")
@click.argument("pipeline", type=click.Path(dir_okay=False, allow_dash=True))
@click.option("--platform", type=click.Choice(["auto", "github", "gitlab"]), default="auto")
@click.option("--gitlab-root", type=click.Path(exists=True, file_okay=False))
def ci_graph(pipeline: str, platform: str, gitlab_root: str | None) -> None:
    """Emit local CI job dependencies as JSON without executing the pipeline."""
    import json

    from radea.core.config import Config
    from radea.static_review.ci_graph import graph

    try:
        report = graph(pipeline, Config.from_env().max_input_bytes, platform, gitlab_root)
    except (ValueError, OSError) as error:
        raise click.ClickException(str(error)) from None
    click.echo(json.dumps(report, indent=2))


@main.command("ci-diff")
@click.argument("before", type=click.Path(dir_okay=False, allow_dash=True))
@click.argument("after", type=click.Path(dir_okay=False, allow_dash=True))
@click.option("--before-platform", type=click.Choice(["auto", "github", "gitlab"]), default="auto")
@click.option("--after-platform", type=click.Choice(["auto", "github", "gitlab"]), default="auto")
@click.option("--before-gitlab-root", type=click.Path(exists=True, file_okay=False))
@click.option("--after-gitlab-root", type=click.Path(exists=True, file_okay=False))
@click.option("--fail-on-change", is_flag=True, help="Exit 2 on changes or unresolved topology.")
def ci_diff(
    before: str, after: str, before_platform: str, after_platform: str, fail_on_change: bool,
    before_gitlab_root: str | None, after_gitlab_root: str | None,
) -> None:
    """Compare job dependencies across two CI configurations and emit JSON."""
    import json

    from radea.core.config import Config
    from radea.static_review.ci_graph import compare

    try:
        report = compare(
            before, after, Config.from_env().max_input_bytes, before_platform, after_platform,
            before_gitlab_root=before_gitlab_root, after_gitlab_root=after_gitlab_root,
        )
    except (ValueError, OSError) as error:
        raise click.ClickException(str(error)) from None
    click.echo(json.dumps(report, indent=2))
    if fail_on_change and any(report[key] for key in ("added", "removed", "modified", "partial")):
        raise click.exceptions.Exit(2)


@main.command("ci-observe")
@click.argument("logs", nargs=-1, required=True, type=click.Path(allow_dash=True))
@click.option("--threshold", type=click.IntRange(1, 20_000), default=3, show_default=True)
@click.option("--watch", type=click.IntRange(1, 3600), help="Poll log snapshots every N seconds.")
def ci_observe(logs: tuple[str, ...], threshold: int, watch: int | None) -> None:
    """Aggregate CI failure signatures and emit threshold transitions."""
    import json
    import time

    from radea.core.config import Config
    from radea.incident_triage.anomalies import transitions
    from radea.pipeline_debug.observe import observe

    limit = Config.from_env().max_input_bytes
    if watch is None:
        try:
            report = observe(logs, limit, threshold)
        except (ValueError, OSError) as error:
            raise click.ClickException(str(error)) from None
        click.echo(json.dumps(report, indent=2))
        return
    if "-" in logs:
        raise click.UsageError("--watch requires files or directories")
    active: set[str] = set()
    last_error = None
    while True:
        try:
            report = observe(logs, limit, threshold)
            if report["skipped"] or report["clipped_lines"]:
                raise ValueError("Incomplete CI log snapshot")
        except (ValueError, OSError) as error:
            message = str(error)
            if message != last_error:
                click.echo(json.dumps({"event": "input_error", "error": message}), err=True)
            last_error = message
        else:
            if last_error is not None:
                click.echo(json.dumps({"event": "input_recovered"}), err=True)
                last_error = None
            for event in transitions(report["categories"], active):
                click.echo(json.dumps({"observed_at": time.time(), **event}))
        time.sleep(watch)


@main.command("ci-timing")
@click.argument("measurements", type=click.Path(dir_okay=False, allow_dash=True))
def ci_timing(measurements: str) -> None:
    """Compare feedback time, concurrency and cache observations across CI runs."""
    import json

    from radea.core.config import Config
    from radea.static_review.ci_timing import analyse

    try:
        report = analyse(measurements, Config.from_env().max_input_bytes)
    except (ValueError, OSError) as error:
        raise click.ClickException(str(error)) from None
    click.echo(json.dumps(report, indent=2))


@main.command("ci-shadow")
@click.argument("baseline", type=click.Path(dir_okay=False, allow_dash=True))
@click.argument("candidate", type=click.Path(dir_okay=False, allow_dash=True))
@click.option("--baseline-build", type=click.Path(dir_okay=False, allow_dash=True))
@click.option("--candidate-build", type=click.Path(dir_okay=False, allow_dash=True))
@click.option("--fail-on-change", is_flag=True, help="Exit 2 on changed tests or artifacts.")
def ci_shadow(
    baseline: str, candidate: str, fail_on_change: bool,
    baseline_build: str | None, candidate_build: str | None,
) -> None:
    """Compare JUnit outcomes collected from baseline and candidate pipelines."""
    import json

    from radea.core.config import Config
    from radea.static_review.ci_shadow import compare

    try:
        report = compare(
            baseline, candidate, Config.from_env().max_input_bytes,
            baseline_build=baseline_build, candidate_build=candidate_build,
        )
    except (ValueError, OSError) as error:
        raise click.ClickException(str(error)) from None
    click.echo(json.dumps(report, indent=2))
    if fail_on_change and (report["changes"] or report.get("build", {}).get("artifact_changes")):
        raise click.exceptions.Exit(2)


@main.command("ci-translate")
@click.argument("source", type=click.Path(dir_okay=False, allow_dash=True))
@click.option("--from-platform", type=click.Choice(["github", "gitlab"]), default="gitlab")
@click.option("--image", help="Digest-pinned GitLab runner image for GitHub source workflows.")
def ci_translate(source: str, from_platform: str, image: str | None) -> None:
    """Draft a manual CI configuration from simple cross-platform shell jobs."""
    import json

    from radea.core.config import Config
    from radea.static_review.ci_translate import translate, translate_github

    if (from_platform == "github") != (image is not None):
        raise click.UsageError("--image is required for GitHub source workflows only")
    try:
        limit = Config.from_env().max_input_bytes
        workflow = translate_github(source, image, limit) if image is not None else translate(
            source, limit,
        )
    except (ValueError, OSError) as error:
        raise click.ClickException(str(error)) from None
    click.echo(json.dumps(workflow, indent=2))


@main.command("tf-review")
@click.argument("paths", nargs=-1, required=True, type=click.Path(allow_dash=True))
@_static_options
def tf_review(paths: tuple[str, ...], output: str, fail_on: str) -> None:
    """Review Terraform source: open ingress, literal secrets, public or unencrypted data,
    unpinned providers and modules, and missing destroy guards (no model, no cloud access).

    PATHS are .tf files, directories or `-` for stdin. For plans use iac-review and policy-check.
    """
    from radea.core.config import Config
    from radea.static_review.runner import run_terraform

    limit = Config.from_env().max_input_bytes
    _finish(lambda: run_terraform(paths, limit), output, fail_on)


@main.command("rightsize")
@click.argument("usage", nargs=-1, required=True, type=click.Path(allow_dash=True))
@_static_options
def rightsize(usage: tuple[str, ...], output: str, fail_on: str) -> None:
    """Compare requests and limits with observed p95/p99 usage and recommend new values.

    USAGE is a JSON list of {workload, container, cpu:{p95}, memory:{p99,max}, requests, limits}.
    Recommendations are advice with their derivation shown; nothing is applied.
    """
    from radea.core.config import Config
    from radea.static_review.runner import run_rightsize

    limit = Config.from_env().max_input_bytes
    _finish(lambda: run_rightsize(usage, limit), output, fail_on)


@main.command("changelog")
@click.option("--repo", default=".", show_default=True, type=click.Path(file_okay=False))
@click.option("--from", "start", default=None, help="Start ref (exclusive), e.g. the last tag.")
@click.option("--to", "end", default="HEAD", show_default=True, help="End ref (inclusive).")
@click.option("--output", type=click.Choice(["markdown", "json"]), default="markdown")
def changelog(repo: str, start: str | None, end: str, output: str) -> None:
    """Draft a changelog and release notes from git history, with a commit-hygiene report.

    Always a draft: a human approves it before it is published.
    """
    import json

    from radea.static_review import changelog as module

    try:
        report = module.build(repo, start, end)
    except ValueError as error:
        raise click.ClickException(str(error)) from None
    click.echo(json.dumps(report, indent=2) if output == "json" else module.render_markdown(report))


@main.command("threat-review")
@click.argument("model", type=click.Path(dir_okay=False, allow_dash=True))
@_static_options
def threat_review(model: str, output: str, fail_on: str) -> None:
    """Draft defensive STRIDE review items from declared data flows and controls."""
    from radea.core.config import Config
    from radea.static_review.threat import review

    _finish(lambda: review(model, Config.from_env().max_input_bytes), output, fail_on)


@main.command("threat-disposition")
@click.argument("draft", type=click.Path(dir_okay=False, allow_dash=True))
@click.argument("decisions", type=click.Path(dir_okay=False, allow_dash=True))
@click.option("--require-complete", is_flag=True, help="Exit 2 if any finding is pending.")
def threat_disposition(draft: str, decisions: str, require_complete: bool) -> None:
    """Record human dispositions against an exact threat review draft."""
    import json

    from radea.core.config import Config
    from radea.static_review.threat import dispositions

    try:
        report = dispositions(draft, decisions, Config.from_env().max_input_bytes)
    except (ValueError, OSError) as error:
        raise click.ClickException(str(error)) from None
    click.echo(json.dumps(report, indent=2))
    if require_complete and report["pending"]:
        raise click.exceptions.Exit(2)


@main.command("gateway-route")
@click.option("--namespace", required=True)
@click.option("--route", required=True)
@click.option("--gateway", required=True)
@click.option("--gateway-namespace")
@click.option("--listener")
@click.option("--hostname")
@click.option("--shadow-reads", is_flag=True, help="Mirror GET and HEAD to the candidate.")
@click.option("--stable", required=True)
@click.option("--candidate", required=True)
@click.option("--port", type=click.IntRange(1, 65535), default=8080, show_default=True)
@click.option("--weight", type=click.IntRange(0, 100), default=0, show_default=True)
@click.option("--path-prefix", default="/", show_default=True)
def gateway_route(
    namespace: str, route: str, gateway: str, stable: str, candidate: str, port: int,
    weight: int, path_prefix: str, gateway_namespace: str | None, listener: str | None,
    hostname: str | None, shadow_reads: bool,
) -> None:
    """Render a Gateway API HTTPRoute for two Services on a path prefix."""
    import json

    from radea.gateway_rollout import emit_route

    try:
        document = emit_route(
            namespace, route, gateway, stable, candidate, port, weight, path_prefix,
            gateway_namespace, listener, hostname, shadow_reads,
        )
    except ValueError as error:
        raise click.ClickException(str(error)) from None
    click.echo(json.dumps(document, indent=2))


@main.command("gateway-rollout")
@click.option("--kubeconfig", required=True, type=click.Path(exists=True, dir_okay=False))
@click.option("--context", required=True)
@click.option("--namespace", required=True)
@click.option("--route", required=True)
@click.option("--stable", required=True)
@click.option("--candidate", required=True)
@click.option("--rule-index", type=click.IntRange(0, 63), default=0, show_default=True)
@click.option("--weight", type=click.IntRange(0, 100))
@click.option("--prometheus", help="Base URL of the Prometheus query API.")
@click.option("--policy", type=click.Path(exists=True, dir_okay=False))
@click.option("--wait-seconds", type=click.IntRange(0, 3600), default=0, show_default=True)
@click.option("--apply", is_flag=True, help="Apply the decision to the HTTPRoute.")
def gateway_rollout(
    kubeconfig: str, context: str, namespace: str, route: str, stable: str, candidate: str,
    rule_index: int, weight: int | None, prometheus: str | None, policy: str | None,
    wait_seconds: int, apply: bool,
) -> None:
    """Stage or evaluate a live Gateway rollout. Hold exits 3 and rollback exits 2."""
    import json
    import time

    from radea.core.config import Config
    from radea.gateway_rollout import load_policy, rollout

    if wait_seconds and weight is not None:
        raise click.UsageError("--wait-seconds requires a telemetry policy")
    deadline = time.monotonic() + wait_seconds
    applied_steps = []
    try:
        thresholds = load_policy(policy, Config.from_env().max_input_bytes) if policy else None
        while True:
            report = rollout(
                kubeconfig, context, namespace, route, stable, candidate, rule_index,
                weight, prometheus, thresholds, apply,
            )
            if report["applied"]:
                applied_steps.append(report["candidate_weight"])
            remaining = deadline - time.monotonic()
            if (
                remaining <= 0
                or report["decision"] not in ("hold", "advance")
                or (report["decision"] == "advance" and not apply)
            ):
                break
            time.sleep(min(5, remaining))
    except (OSError, ValueError) as error:
        raise click.ClickException(str(error)) from None
    report["applied_steps"] = applied_steps
    click.echo(json.dumps(report, indent=2))
    raise click.exceptions.Exit({"rollback": 2, "hold": 3, "advance": 3}.get(report["decision"], 0))


@main.command("canary-gate")
@click.argument("measurements", type=click.Path(dir_okay=False, allow_dash=True))
@click.option("--min-requests", type=click.IntRange(1, 100_000), default=100, show_default=True)
@click.option("--min-success-rate", type=click.FloatRange(0, 1), default=0.99, show_default=True)
@click.option("--max-p95-ms", type=click.FloatRange(0), required=True)
def canary_gate(
    measurements: str, min_requests: int, min_success_rate: float, max_p95_ms: float
) -> None:
    """Decide promote (0), rollback (2), or hold for more observations (3)."""
    import json

    from radea.core.config import Config
    from radea.incident_triage.canary import decide

    try:
        report = decide(
            measurements, Config.from_env().max_input_bytes, min_requests,
            min_success_rate, max_p95_ms,
        )
    except (ValueError, OSError) as error:
        raise click.ClickException(str(error)) from None
    click.echo(json.dumps(report, indent=2))
    if report["decision"] != "promote":
        raise click.exceptions.Exit({"rollback": 2, "hold": 3}[report["decision"]])


@main.command("cost-report")
@click.argument("export", type=click.Path(dir_okay=False, allow_dash=True))
@click.option("--by", "dimensions", multiple=True, help="FOCUS dimension column.")
@click.option("--tag", help="Key to read from the JSON Tags column.")
@click.option("--baseline", type=click.Path(dir_okay=False, allow_dash=True),
              help="Compare against a comparable earlier export.")
def cost_report(
    export: str, dimensions: tuple[str, ...], tag: str | None, baseline: str | None,
) -> None:
    """Attribute billed cost by dimension or tag from a local FOCUS CSV export."""
    import json

    from radea.core.config import Config
    from radea.incident_triage.costs import allocate, compare

    if len(dimensions) > 8 or len(set(dimensions)) != len(dimensions):
        raise click.UsageError("Use up to eight distinct dimension columns")
    if tag is not None and (not tag or f"tag:{tag}" in dimensions):
        raise click.UsageError("Use a nonempty tag distinct from the requested dimensions")
    try:
        limit = Config.from_env().max_input_bytes
        report = (
            allocate(export, dimensions, tag, limit) if baseline is None
            else compare(baseline, export, dimensions, tag, limit)
        )
    except (ValueError, OSError) as error:
        raise click.ClickException(str(error)) from None
    click.echo(json.dumps(report, indent=2))


@main.command("dora-report")
@click.argument("events", type=click.Path(dir_okay=False, allow_dash=True))
def dora_report(events: str) -> None:
    """Calculate five delivery metrics from local production deployment events."""
    import json

    from radea.core.config import Config
    from radea.incident_triage.dora import analyse

    try:
        report = analyse(events, Config.from_env().max_input_bytes)
    except (ValueError, OSError) as error:
        raise click.ClickException(str(error)) from None
    click.echo(json.dumps(report, indent=2))


@main.command("prompt-prepare")
@click.argument("library", type=click.Path(dir_okay=False, allow_dash=True))
@click.argument("context", type=click.Path(dir_okay=False, allow_dash=True))
@click.option("--template", "template_id", required=True)
@click.option("--version", required=True)
def prompt_prepare(library: str, context: str, template_id: str, version: str) -> None:
    """Prepare a versioned prompt packet from a team library."""
    import json

    from radea.core.config import Config
    from radea.prompt_kit import prepare

    try:
        report = prepare(library, context, template_id, version, Config.from_env().max_input_bytes)
    except (ValueError, OSError) as error:
        raise click.ClickException(str(error)) from None
    click.echo(json.dumps(report, indent=2))


@main.command("postmortem-review")
@click.argument("draft", type=click.Path(dir_okay=False, allow_dash=True))
@click.argument("decisions", type=click.Path(dir_okay=False, allow_dash=True))
def postmortem_review(draft: str, decisions: str) -> None:
    """Bind human incident decisions and action items to a specific triage draft."""
    import json

    from radea.core.config import Config
    from radea.incident_triage.postmortem import review

    try:
        report = review(draft, decisions, Config.from_env().max_input_bytes)
    except (ValueError, OSError) as error:
        raise click.ClickException(str(error)) from None
    click.echo(json.dumps(report, indent=2))


@main.command("telemetry-capture")
@click.argument("destination", type=click.Path(file_okay=False))
@click.option("--port", type=click.IntRange(0, 65535), default=4318, show_default=True)
def telemetry_capture(destination: str, port: int) -> None:
    """Collect minimal OTLP/HTTP JSON correlation fields on loopback."""
    import json
    from pathlib import Path

    from radea.core.config import Config
    from radea.incident_triage.otlp_capture import CaptureServer

    try:
        output = Path(destination)
        limit = Config.from_env().max_input_bytes
        with CaptureServer(output, port, limit) as server:
            output.mkdir(mode=0o700)
            click.echo(json.dumps({
                "endpoint": f"http://127.0.0.1:{server.server_port}", "destination": str(output),
            }))
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                return
    except (ValueError, OSError) as error:
        raise click.ClickException(str(error)) from None


@main.command("telemetry-review")
@click.argument("traces", type=click.Path(dir_okay=False, allow_dash=True))
@click.option("--logs", type=click.Path(dir_okay=False, allow_dash=True))
@click.option("--metrics", type=click.Path(dir_okay=False, allow_dash=True))
def telemetry_review(traces: str, logs: str | None, metrics: str | None) -> None:
    """Correlate spans, log records and metric exemplars from local OTLP captures."""
    import json

    from radea.core.config import Config
    from radea.incident_triage.telemetry import analyse

    if (traces, logs, metrics).count("-") > 1:
        raise click.UsageError("Only one capture may use stdin")
    try:
        report = analyse(traces, logs, metrics, Config.from_env().max_input_bytes)
    except (ValueError, OSError) as error:
        raise click.ClickException(str(error)) from None
    click.echo(json.dumps(report, indent=2))


@main.command("pilot-report")
@click.argument("cases", type=click.Path(dir_okay=False, allow_dash=True))
def pilot_report(cases: str) -> None:
    """Compare measured baseline time with assisted execution, verification and rework."""
    import json

    from radea.core.config import Config
    from radea.core.sanitizer import clean
    from radea.pilot import analyse

    try:
        report = analyse(cases, Config.from_env().max_input_bytes)
    except (ValueError, OSError) as error:
        raise click.ClickException(str(error)) from None
    click.echo(json.dumps(clean(report), indent=2))


@main.command("metric-anomalies")
@click.argument("series", type=click.Path(dir_okay=False, allow_dash=True))
@click.option("--window", type=click.IntRange(5, 10_000), default=10, show_default=True)
@click.option("--threshold", type=click.FloatRange(0.1, 100), default=3.5, show_default=True)
@click.option("--relative-floor", type=click.FloatRange(0, 1), default=0.05, show_default=True)
@click.option("--prometheus", metavar="URL", help="Fetch readings for named Prometheus queries.")
@click.option(
    "--step", type=click.IntRange(1, 3600),
    help="Prometheus sample interval in seconds (default: 60).",
)
@click.option(
    "--watch", type=click.IntRange(1, 3600), help="Emit alert transitions every N seconds."
)
@click.option("--fail-on-anomaly", is_flag=True, help="Exit 2 when any metric is anomalous.")
def metric_anomalies(
    series: str, window: int, threshold: float, relative_floor: float, fail_on_anomaly: bool,
    watch: int | None, prometheus: str | None, step: int | None,
) -> None:
    """Detect outliers in supplied metrics using a rolling median and MAD."""
    import json
    import time

    from radea.core.config import Config
    from radea.incident_triage.anomalies import analyse, transitions

    if step is not None and prometheus is None:
        raise click.UsageError("--step requires --prometheus")
    max_bytes = Config.from_env().max_input_bytes

    def read_metrics() -> dict:
        return analyse(
            series, max_bytes, window, threshold, relative_floor,
            prometheus=prometheus, step=step or 60, now=int(time.time()),
        )

    if watch is not None:
        if series == "-" or fail_on_anomaly:
            raise click.UsageError("--watch requires a file and cannot use --fail-on-anomaly")
        active: set[str] = set()
        last_error = None
        while True:
            try:
                report = read_metrics()
            except (ValueError, OSError) as error:
                message = str(error)
                if message != last_error:
                    click.echo(json.dumps({"event": "input_error", "error": message}), err=True)
                last_error = message
            else:
                if last_error is not None:
                    click.echo(json.dumps({"event": "input_recovered"}), err=True)
                    last_error = None
                for event in transitions(report["metrics"], active):
                    click.echo(json.dumps({"observed_at": time.time(), **event}))
            time.sleep(watch)

    try:
        report = read_metrics()
    except (ValueError, OSError) as error:
        raise click.ClickException(str(error)) from None
    click.echo(json.dumps(report, indent=2))
    if fail_on_anomaly and any(item["anomaly"] for item in report["metrics"]):
        raise click.exceptions.Exit(2)


@main.command("rebuild-check")
@click.argument("baseline", type=click.Path(dir_okay=False, allow_dash=True))
@click.argument("rebuilt", type=click.Path(dir_okay=False, allow_dash=True))
@click.option("--fail-on-change", is_flag=True, help="Exit 2 on drift or missing categories.")
def rebuild_check(baseline: str, rebuilt: str, fail_on_change: bool) -> None:
    """Compare package, service, config hash and probe inventories after a rebuild."""
    import json

    from radea.core.config import Config
    from radea.static_review.rebuild import compare

    try:
        report = compare(baseline, rebuilt, Config.from_env().max_input_bytes)
    except (ValueError, OSError) as error:
        raise click.ClickException(str(error)) from None
    click.echo(json.dumps(report, indent=2))
    if fail_on_change and not report["matches"]:
        raise click.exceptions.Exit(2)


@main.command("tf-plan-diff")
@click.argument("baseline", type=click.Path(exists=True, dir_okay=False))
@click.argument("candidate", type=click.Path(exists=True, dir_okay=False))
@click.option("--fail-on-change", is_flag=True, help="Exit 2 on differences or incomplete plans.")
def tf_plan_diff(baseline: str, candidate: str, fail_on_change: bool) -> None:
    """Compare Terraform plans without printing attribute names or values."""
    import json

    from radea.core.config import Config
    from radea.iac_review.plan import compare_plans

    try:
        report = compare_plans(baseline, candidate, Config.from_env().max_input_bytes)
    except (ValueError, OSError, RecursionError) as error:
        raise click.ClickException(str(error)) from None
    click.echo(json.dumps(report, indent=2))
    if fail_on_change and (report["changes"] or report["incomplete"]):
        raise click.exceptions.Exit(2)


@main.command("tf-drift")
@click.argument("plan", type=click.Path(exists=True, dir_okay=False))
@click.option("--fail-on-drift", is_flag=True, help="Exit 2 on drift or an incomplete plan.")
def tf_drift(plan: str, fail_on_drift: bool) -> None:
    """Report refresh drift from Terraform plan JSON without attribute values."""
    import json

    from radea.core.config import Config
    from radea.core.sanitizer import clean
    from radea.iac_review.plan import inspect_drift

    try:
        report = inspect_drift(plan, Config.from_env().max_input_bytes)
    except (ValueError, OSError) as error:
        raise click.ClickException(str(error)) from None
    click.echo(json.dumps(clean(report), indent=2))
    if fail_on_drift and (report["drift"] or report["incomplete"]):
        raise click.exceptions.Exit(2)


@main.command("mutation-suite")
@click.argument("root", type=click.Path(exists=True, file_okay=False))
@click.option("--package", required=True, help="Package directory relative to root.")
@click.option("--tests", required=True, help="Test directory relative to root.")
@click.option("--max-mutants", type=click.IntRange(1, 100), default=20, show_default=True)
@click.option("--timeout", type=click.IntRange(1, 120), default=10, show_default=True)
@click.option("--fail-on-survival", is_flag=True)
def mutation_suite(
    root: str, package: str, tests: str, max_mutants: int, timeout: int, fail_on_survival: bool
) -> None:
    """Run a trusted Python package test suite against per-module mutations."""
    import json

    from radea.core.config import Config
    from radea.static_review.mutation import suite

    try:
        report = suite(
            root, package, tests, Config.from_env().max_input_bytes, max_mutants, timeout
        )
    except (ValueError, OSError) as error:
        raise click.ClickException(str(error)) from None
    click.echo(json.dumps(report, indent=2))
    if fail_on_survival and (
        report["survived"] or report["inconclusive"]
        or report["tested_mutants"] < report["available_mutants"]
    ):
        raise click.exceptions.Exit(2)


@main.command("mutation-test")
@click.argument("module", type=click.Path(exists=True, dir_okay=False))
@click.argument("tests", type=click.Path(exists=True, dir_okay=False))
@click.option("--max-mutants", type=click.IntRange(1, 100), default=20, show_default=True)
@click.option("--timeout", type=click.IntRange(1, 120), default=10, show_default=True)
@click.option("--fail-on-survival", is_flag=True, help="Exit 2 on survival or incomplete coverage.")
def mutation_test(
    module: str, tests: str, max_mutants: int, timeout: int, fail_on_survival: bool
) -> None:
    """Run pytest on small mutations of a self-contained trusted Python module."""
    import json

    from radea.core.config import Config
    from radea.static_review.mutation import test

    try:
        report = test(module, tests, Config.from_env().max_input_bytes, max_mutants, timeout)
    except (ValueError, OSError) as error:
        raise click.ClickException(str(error)) from None
    click.echo(json.dumps(report, indent=2))
    if fail_on_survival and (
        report["survived"] or report["inconclusive"]
        or report["tested_mutants"] < report["available_mutants"]
    ):
        raise click.exceptions.Exit(2)


@main.command("code-review")
@click.argument("paths", nargs=-1, required=True, type=click.Path(allow_dash=True))
@click.option("--baseline", type=click.Path(dir_okay=False, allow_dash=True),
              help="Report findings on changed lines of one candidate file.")
@click.option("--output", type=click.Choice(["text", "json"]), default="text")
@click.option("--fail-on", type=click.Choice(["high", "medium", "low", "never"]), default="never")
def code_review(paths: tuple[str, ...], output: str, fail_on: str, baseline: str | None) -> None:
    """Report mechanical Python code defects without executing the source."""
    from radea.core.config import Config
    from radea.static_review.code import review

    _finish(
        lambda: review(paths, Config.from_env().max_input_bytes, baseline=baseline),
        output, fail_on,
    )


@main.command("cutover-plan")
@click.argument("source", type=click.Path(dir_okay=False, allow_dash=True))
@click.option("--fail-at", help="Simulate a failed verification at this step.")
def cutover_plan(source: str, fail_at: str | None) -> None:
    """Validate a cutover runbook and simulate the rollback order."""
    import json

    from radea.core.config import Config
    from radea.cutover import plan

    try:
        report = plan(source, fail_at, Config.from_env().max_input_bytes)
    except (ValueError, OSError) as error:
        raise click.ClickException(str(error)) from None
    click.echo(json.dumps(report, indent=2))


@main.command("cutover-rehearse")
@click.option("--kubeconfig", required=True, type=click.Path(exists=True, dir_okay=False))
@click.option("--context", required=True)
@click.option("--namespace", required=True)
@click.option("--route", required=True)
@click.option("--stable", required=True)
@click.option("--candidate", required=True)
@click.option("--rule-index", type=click.IntRange(0, 63), default=0)
@click.option("--origin", required=True)
@click.option("--path", required=True)
@click.option("--stable-body", required=True)
@click.option("--candidate-body", required=True)
@click.option("--weight", "weights", multiple=True, type=click.IntRange(1, 100),
              default=(25, 50, 100), show_default=True)
@click.option("--fail-at", type=click.IntRange(1, 100), help="Inject a failure at this weight.")
@click.option("--samples", type=click.IntRange(3, 120), default=12, show_default=True)
@click.option("--apply", is_flag=True, help="Explicitly allow temporary staging traffic changes.")
def cutover_rehearse(
    kubeconfig: str, context: str, namespace: str, route: str, stable: str, candidate: str,
    rule_index: int, origin: str, path: str, stable_body: str, candidate_body: str,
    weights: tuple[int, ...], fail_at: int | None, samples: int, apply: bool,
) -> None:
    """Rehearse an HTTPRoute cutover on staging, then restore and probe stable."""
    import json

    from radea.cutover_rehearsal import rehearse

    if not apply:
        raise click.UsageError("Rehearsal changes traffic temporarily. Use --apply on staging.")
    try:
        report = rehearse(
            (kubeconfig, context, namespace, route, stable, candidate, rule_index),
            origin, path, stable_body, candidate_body, weights, fail_at, samples,
        )
    except (OSError, ValueError) as error:
        raise click.ClickException(str(error)) from None
    click.echo(json.dumps(report, indent=2))
    if not report["passed"]:
        raise click.exceptions.Exit(2)


@main.command("flag-evaluate")
@click.argument("config", type=click.Path(dir_okay=False, allow_dash=True))
@click.argument("flag")
@click.option("--cohort", required=True)
@click.option("--group", "groups", multiple=True)
def flag_evaluate(config: str, flag: str, cohort: str, groups: tuple[str, ...]) -> None:
    """Evaluate a feature flag for a stable caller and its trusted groups."""
    import json

    from radea.core.config import Config
    from radea.feature_flags import evaluate

    try:
        report = evaluate(config, flag, cohort, groups, Config.from_env().max_input_bytes)
    except (ValueError, OSError) as error:
        raise click.ClickException(str(error)) from None
    click.echo(json.dumps(report, indent=2))


@main.command("flag-experiment")
@click.argument("observations", type=click.Path(dir_okay=False, allow_dash=True))
@click.option("--control", required=True)
def flag_experiment(observations: str, control: str) -> None:
    """Compare observed feature flag outcomes with a control variant."""
    import json

    from radea.core.config import Config
    from radea.feature_flags import experiment

    try:
        report = experiment(observations, control, Config.from_env().max_input_bytes)
    except (ValueError, OSError) as error:
        raise click.ClickException(str(error)) from None
    click.echo(json.dumps(report, indent=2))


@main.command("migration-serve")
@click.argument("plan", type=click.Path(exists=True, dir_okay=False))
@click.option("--port", type=click.IntRange(0, 65535), default=8080, show_default=True)
@click.option("--legacy-port", type=click.IntRange(1, 65535), required=True)
@click.option("--candidate-port", type=click.IntRange(1, 65535), required=True)
def migration_serve(plan: str, port: int, legacy_port: int, candidate_port: int) -> None:
    """Serve a local read-only migration facade with deterministic cohort routing."""
    import json

    from radea.core.config import Config
    from radea.migration_facade import Facade

    try:
        with Facade(plan, port, legacy_port, candidate_port,
                    Config.from_env().max_input_bytes) as server:
            click.echo(json.dumps({"endpoint": f"http://127.0.0.1:{server.server_port}"}))
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                return
    except (ValueError, OSError) as error:
        raise click.ClickException(str(error)) from None


@main.command("migration-parity")
@click.option("--legacy", required=True, help="Legacy backend origin.")
@click.option("--candidate", required=True, help="Candidate backend origin.")
@click.option("--path", required=True, help="Read-only path to compare.")
def migration_parity(legacy: str, candidate: str, path: str) -> None:
    """Compare responses on a migration slice. Differences exit 2."""
    import json

    from radea.core.config import Config
    from radea.migration_parity import compare

    try:
        report = compare(legacy, candidate, path, Config.from_env().max_input_bytes)
    except ValueError as error:
        raise click.ClickException(str(error)) from None
    click.echo(json.dumps(report, indent=2))
    if not report["matches"]:
        raise click.exceptions.Exit(2)


@main.command("migration-route")
@click.argument("plan", type=click.Path(dir_okay=False, allow_dash=True))
@click.option("--path", required=True)
@click.option("--cohort", required=True, help="Stable caller or request group identifier.")
def migration_route(plan: str, path: str, cohort: str) -> None:
    """Preview a legacy or candidate route for a staged migration."""
    import json

    from radea.core.config import Config
    from radea.migration import decide

    try:
        report = decide(plan, path, cohort, Config.from_env().max_input_bytes)
    except (ValueError, OSError) as error:
        raise click.ClickException(str(error)) from None
    click.echo(json.dumps(report, indent=2))


@main.command("service-scaffold")
@click.argument("destination", type=click.Path(file_okay=False))
@click.option("--name", required=True)
@click.option("--base-image", required=True, help="Python base image pinned by SHA-256.")
@click.option("--owner", help="Generate a Backstage descriptor for this catalog group.")
def service_scaffold(destination: str, name: str, base_image: str, owner: str | None) -> None:
    """Create a local Python HTTP service starter for review."""
    from pathlib import Path

    from radea.scaffold import scaffold

    try:
        created = scaffold(name, base_image, Path(destination), owner=owner)
    except (ValueError, OSError) as error:
        raise click.ClickException(str(error)) from None
    for path in created:
        click.echo(path)


@main.command("docs-answer")
@click.argument("question")
@click.argument("paths", nargs=-1, required=True, type=click.Path())
@click.option("--max-sources", type=click.IntRange(1, 10), default=3, show_default=True)
@click.option("--gap-log", type=click.Path(dir_okay=False))
@click.option("--topic", help="Category to count when documentation has no match.")
def docs_answer(
    question: str, paths: tuple[str, ...], max_sources: int,
    gap_log: str | None, topic: str | None,
) -> None:
    """Find cited passages in local platform docs or report no documented answer."""
    import json

    from radea.core.config import Config
    from radea.helpdesk import answer, log_gap

    if (gap_log is None) != (topic is None):
        raise click.UsageError("--gap-log and --topic must be supplied together")
    try:
        report = answer(question, paths, Config.from_env().max_input_bytes, max_sources)
        if gap_log is not None and topic is not None and report["status"] == "no_documented_answer":
            log_gap(gap_log, topic)
    except (ValueError, OSError) as error:
        raise click.ClickException(str(error)) from None
    click.echo(json.dumps(report, indent=2, ensure_ascii=False))


@main.command("docs-backlog")
@click.argument("log", type=click.Path(dir_okay=False, allow_dash=True))
def docs_backlog(log: str) -> None:
    """Rank documentation gap categories by unanswered requests."""
    import json

    from radea.core.config import Config
    from radea.helpdesk import backlog

    try:
        report = backlog(log, Config.from_env().max_input_bytes)
    except (ValueError, OSError) as error:
        raise click.ClickException(str(error)) from None
    click.echo(json.dumps(report, indent=2))


@main.command("test-scaffold")
@click.argument("specification", type=click.Path(dir_okay=False, allow_dash=True))
@click.option("--module", required=True)
@click.option("--function", required=True)
def test_scaffold(specification: str, module: str, function: str) -> None:
    """Generate pytest source from explicit input and expected-output examples."""
    from radea.core.config import Config
    from radea.static_review.test_scaffold import render

    try:
        source = render(specification, module, function, Config.from_env().max_input_bytes)
    except (ValueError, OSError) as error:
        raise click.ClickException(str(error)) from None
    click.echo(source, nl=False)


@main.command("test-review")
@click.argument("paths", nargs=-1, required=True, type=click.Path(allow_dash=True))
@_static_options
def test_review(paths: tuple[str, ...], output: str, fail_on: str) -> None:
    """Find tests that cannot fail: no assertion, always-true assertions, empty or swallowing tests.

    PATHS are test files or directories (Python test_*.py / *_test.py, Java and Kotlin *Test).
    """
    from radea.core.config import Config
    from radea.static_review.runner import run_tests

    limit = Config.from_env().max_input_bytes
    _finish(lambda: run_tests(paths, limit), output, fail_on)


@main.command("iam-simulation-review")
@click.argument("simulation", type=click.Path(dir_okay=False, allow_dash=True))
@click.argument("expectations", type=click.Path(dir_okay=False, allow_dash=True))
@click.option("--fail-on-mismatch", is_flag=True, help="Exit 2 on unexpected or unknown decisions.")
def iam_simulation_review(simulation: str, expectations: str, fail_on_mismatch: bool) -> None:
    """Check saved AWS IAM policy simulation results against expected permissions."""
    import json

    from radea.core.config import Config
    from radea.core.sanitizer import clean
    from radea.static_review.iam_simulation import review

    try:
        report = review(simulation, expectations, Config.from_env().max_input_bytes)
    except (ValueError, OSError) as error:
        raise click.ClickException(str(error)) from None
    click.echo(json.dumps(clean(report), indent=2))
    if fail_on_mismatch and not report["passed"]:
        raise click.exceptions.Exit(2)


@main.command("repo-contract-check")
@click.argument("manifests", nargs=-1, required=True,
                type=click.Path(dir_okay=False, allow_dash=True))
@click.option("--fail-on-change", is_flag=True, help="Exit 2 on missing or mismatched contracts.")
def repo_contract_check(manifests: tuple[str, ...], fail_on_change: bool) -> None:
    """Check exact contract revisions across repositories or monorepo modules."""
    import json

    from radea.core.config import Config
    from radea.static_review.contracts import check

    try:
        report = check(manifests, Config.from_env().max_input_bytes)
    except (ValueError, OSError) as error:
        raise click.ClickException(str(error)) from None
    click.echo(json.dumps(report, indent=2))
    if fail_on_change and report["findings"]:
        raise click.exceptions.Exit(2)


@main.command("secret-migration-plan")
@click.argument("inventory", type=click.Path(dir_okay=False, allow_dash=True))
@click.option("--require-ready", is_flag=True, help="Exit 2 if a migration check remains pending.")
def secret_migration_plan(inventory: str, require_ready: bool) -> None:
    """Review migration ownership, consumer readiness and rotation using metadata."""
    import json

    from radea.core.config import Config
    from radea.static_review.secret_migration import plan

    try:
        report = plan(inventory, Config.from_env().max_input_bytes)
    except (ValueError, OSError) as error:
        raise click.ClickException(str(error)) from None
    click.echo(json.dumps(report, indent=2))
    if require_ready and not report["ready"]:
        raise click.exceptions.Exit(2)


@main.command("dependency-review")
@click.argument("approved", type=click.Path(dir_okay=False, allow_dash=True))
@click.argument("candidate", type=click.Path(dir_okay=False, allow_dash=True))
@click.option("--fail-on-unapproved", is_flag=True, help="Exit 2 on any approval mismatch.")
def dependency_review(approved: str, candidate: str, fail_on_unapproved: bool) -> None:
    """Check package versions, registries and artifact hashes against a trusted inventory."""
    import json

    from radea.core.config import Config
    from radea.static_review.dependencies import review

    try:
        report = review(approved, candidate, Config.from_env().max_input_bytes)
    except (ValueError, OSError) as error:
        raise click.ClickException(str(error)) from None
    click.echo(json.dumps(report, indent=2))
    if fail_on_unapproved and report["findings"]:
        raise click.exceptions.Exit(2)


@main.command("sbom-review")
@click.argument("sbom", type=click.Path(dir_okay=False, allow_dash=True))
@click.argument("scan", type=click.Path(dir_okay=False, allow_dash=True))
@click.option("--runtime", type=click.Path(dir_okay=False, allow_dash=True),
              help="Correlate supplied runtime evidence for the exact SBOM.")
def sbom_review(sbom: str, scan: str, runtime: str | None) -> None:
    """Match Grype or Trivy findings to a CycloneDX JSON SBOM."""
    import json

    from radea.core.config import Config
    from radea.static_review.sbom import analyse

    try:
        report = analyse(sbom, scan, Config.from_env().max_input_bytes, runtime=runtime)
    except (ValueError, OSError) as error:
        raise click.ClickException(str(error)) from None
    click.echo(json.dumps(report, indent=2))


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


@main.group("learn-readiness")
def learn_readiness() -> None:
    """Practice diagnosing and correcting a Kubernetes readiness probe offline."""


@learn_readiness.command("start")
def readiness_start() -> None:
    """Print the starter Deployment YAML for a read-only endpoint on port 8080."""
    from radea.learning import STARTER

    click.echo(STARTER, nl=False)


@learn_readiness.command("hint")
def readiness_hint() -> None:
    """Explain readiness and present a teach-back question."""
    from radea.learning import readiness_feedback

    click.echo(readiness_feedback())


@learn_readiness.command("check")
@click.argument("submission", type=click.Path(exists=True, dir_okay=False))
def readiness_check(submission: str) -> None:
    """Verify the submitted Deployment with RADEA's Kubernetes rules."""
    import json

    from radea.core.config import Config
    from radea.learning import check_readiness

    try:
        report = check_readiness(submission, Config.from_env().max_input_bytes)
    except (OSError, ValueError) as error:
        raise click.ClickException(str(error)) from None
    click.echo(json.dumps(report, indent=2))
    if not report["passed"]:
        raise click.exceptions.Exit(2)


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
