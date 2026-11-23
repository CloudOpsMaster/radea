"""Glue between collected files and the rule modules; one function per review command."""

import os

from radea.static_review.ci import review_ci
from radea.static_review.dockerfile import review_dockerfile
from radea.static_review.files import Source, collect
from radea.static_review.findings import Finding, build_report
from radea.static_review.k8s import Review, review_chart
from radea.static_review.yaml_loader import load_all

K8S_LIMITATIONS = (
    "Static rules over the files given. Helm templates must be rendered first (helm template); "
    "chart source gets chart-level checks only. No cluster state, admission policy or runtime "
    "behaviour is considered, and no findings does not prove the workload is safe."
)


def run_k8s(paths: list[str] | tuple[str, ...], max_bytes: int) -> dict:
    sources, skipped = collect(paths, suffixes=(".yaml", ".yml", ".json"), max_bytes=max_bytes)
    by_path = {s.path: s for s in sources}
    charts = [s for s in sources if os.path.basename(s.path) == "Chart.yaml"]
    chart_files: dict[str, dict[str, Source]] = {}
    chart_dirs: dict[str, str] = {}
    consumed: set[str] = set()
    for chart in charts:
        directory = os.path.dirname(chart.path) or "."
        chart_dirs[chart.path] = directory
        prefix = directory.rstrip(os.sep) + os.sep
        members: dict[str, Source] = {}
        for path, source in by_path.items():
            if path.startswith(prefix) and path != chart.path:
                relative = path[len(prefix) :]
                if relative.startswith(("templates/", "charts/")) or relative == "values.yaml":
                    members[relative] = source
                    consumed.add(path)
        chart_files[chart.path] = members

    review = Review()
    findings: list[Finding] = []
    reviewed: list[Source] = []
    for source in sources:
        if source.path in consumed or os.path.basename(source.path) == "Chart.yaml":
            continue
        reason = review.load(source)
        if reason:
            skipped.append({"path": source.path, "reason": reason})
        elif review.objects.get(source.path):
            reviewed.append(source)
    findings.extend(review.run())
    for chart in charts:
        reviewed.append(chart)
        reviewed.extend(chart_files[chart.path].values())
        chart_dir = chart_dirs[chart.path] if chart.path != "<stdin>" else None
        findings.extend(review_chart(chart, chart_files[chart.path], chart_dir))
    return build_report(
        "k8s-review",
        findings,
        [s.meta() for s in reviewed],
        skipped=skipped,
        limitations=K8S_LIMITATIONS,
    )


DOCKERFILE_LIMITATIONS = (
    "Static rules over the Dockerfile text. Build arguments, multi-stage COPY --from targets and "
    "the base image's own contents are not evaluated; pair this with an image scanner."
)
CI_LIMITATIONS = (
    "Static rules over pipeline files. Platform settings (protected variables, runner trust, "
    "branch protection) are outside the file and are not checked."
)


def run_dockerfile(paths: list[str] | tuple[str, ...], max_bytes: int) -> dict:
    sources, skipped = collect(
        paths,
        suffixes=(".dockerfile",),
        names=("dockerfile", "containerfile"),
        prefixes=("dockerfile.", "containerfile."),
        max_bytes=max_bytes,
    )
    findings: list[Finding] = []
    for source in sources:
        findings.extend(review_dockerfile(source))
    return build_report(
        "dockerfile-review",
        findings,
        [s.meta() for s in sources],
        skipped=skipped,
        limitations=DOCKERFILE_LIMITATIONS,
    )


def run_ci(paths: list[str] | tuple[str, ...], max_bytes: int) -> dict:
    sources, skipped = collect(paths, suffixes=(".yml", ".yaml"), max_bytes=max_bytes)
    findings: list[Finding] = []
    reviewed: list[Source] = []
    for source in sources:
        try:
            documents = load_all(source.text)
        except ValueError as error:
            skipped.append({"path": source.path, "reason": str(error)})
            continue
        found, recognised = review_ci(source, documents)
        if recognised:
            reviewed.append(source)
            findings.extend(found)
    return build_report(
        "ci-review",
        findings,
        [s.meta() for s in reviewed],
        skipped=skipped,
        limitations=CI_LIMITATIONS,
    )
