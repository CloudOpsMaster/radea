"""Render two local Helm charts and compare their manifests across value sets."""

import os
import re
import subprocess
from collections import defaultdict
from pathlib import Path
from tempfile import TemporaryDirectory

from radea.static_review.manifest_diff import compare

ENVIRONMENT = re.compile(r"[a-z0-9][a-z0-9-]{0,62}\Z")


def _local_chart(path: str) -> Path:
    chart = Path(path).resolve()
    if not chart.is_dir() or not (chart / "Chart.yaml").is_file():
        raise ValueError("Expected local chart directories with Chart.yaml")
    return chart


def _render(
    chart: Path, values: list[Path], destination: Path, env: dict[str, str], limit: int
) -> None:
    arguments = ["helm", "template", "radea-review", str(chart), "--include-crds"]
    for path in values:
        arguments.extend(("--values", str(path)))
    with destination.open("wb") as rendered:
        result = subprocess.run(
            arguments,
            stdout=rendered,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            env=env,
            timeout=30,
            check=False,
        )
    if result.returncode != 0:
        raise ValueError("Helm render failed; check chart templates and values compatibility")
    if destination.stat().st_size > limit:
        raise ValueError("Helm render exceeds RADEA_MAX_INPUT_BYTES")


def _environment(work: Path) -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if not key.startswith(("HELM_", "KUBE"))}
    env.update(
        {
            "KUBECONFIG": str(work / "kubeconfig"),
            "HELM_CONFIG_HOME": str(work / "config"),
            "HELM_CACHE_HOME": str(work / "cache"),
            "HELM_DATA_HOME": str(work / "data"),
        }
    )
    return env


def _values(values_paths: tuple[str, ...], limit: int) -> list[Path]:
    values = [Path(path).resolve() for path in values_paths]
    if len(values) > 40 or any(
        not path.is_file() or path.stat().st_size > limit for path in values
    ):
        raise ValueError("Use up to 40 local values files within RADEA_MAX_INPUT_BYTES")
    return values


def review(chart_path: str, values_paths: tuple[str, ...], limit: int) -> dict:
    from radea.static_review.runner import run_k8s

    chart = _local_chart(chart_path)
    values = _values(values_paths, limit)
    try:
        with TemporaryDirectory(prefix="radea-helm-") as directory:
            work = Path(directory)
            env = _environment(work)
            arguments = ["helm", "lint", "--strict", str(chart)]
            for path in values:
                arguments.extend(("--values", str(path)))
            result = subprocess.run(
                arguments,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=env,
                timeout=30,
                check=False,
            )
            if result.returncode:
                raise ValueError(
                    "Helm lint failed; check chart metadata, templates and values schema"
                )
            rendered = work / "rendered.yaml"
            _render(chart, values, rendered, env, limit)
            report = run_k8s((str(chart), str(rendered)), limit)
            report["command"] = "helm-review"
            for entry in [*report["findings"], *report["skipped"]]:
                if entry.get("path") == str(rendered):
                    entry["path"] = "<helm-render>"
            return report
    except subprocess.TimeoutExpired:
        raise ValueError("Helm chart validation timed out") from None


def compare_kustomize(
    chart_path: str, overlay_path: str, values_paths: tuple[str, ...], limit: int
) -> dict:
    chart = _local_chart(chart_path)
    overlay = Path(overlay_path).resolve()
    values = _values(values_paths, limit)
    try:
        with TemporaryDirectory(prefix="radea-render-") as directory:
            work = Path(directory)
            env = _environment(work)
            helm, kustomize = work / "helm.yaml", work / "kustomize.yaml"
            _render(chart, values, helm, env, limit)
            with kustomize.open("wb") as output:
                result = subprocess.run(
                    ["kubectl", "kustomize", str(overlay)],
                    stdin=subprocess.DEVNULL,
                    stdout=output,
                    stderr=subprocess.DEVNULL,
                    env=env,
                    timeout=30,
                    check=False,
                )
            if result.returncode:
                raise ValueError("Kustomize build failed; check overlay resources and patches")
            if kustomize.stat().st_size > limit:
                raise ValueError("Kustomize build exceeds RADEA_MAX_INPUT_BYTES")
            report = compare(str(helm), str(kustomize), limit, allow_empty=True)
            report["sources"]["before"]["path"] = str(chart)
            report["sources"]["after"]["path"] = str(overlay)
            return {**report, "command": "helm-kustomize-diff"}
    except subprocess.TimeoutExpired:
        raise ValueError("Manifest render timed out") from None


def _environment_values(overrides: tuple[str, ...], limit: int) -> dict[str, list[Path]]:
    environments: dict[str, list[Path]] = defaultdict(list)
    for override in overrides:
        name, separator, value = override.partition("=")
        path = Path(value).resolve()
        if (
            not separator
            or not ENVIRONMENT.fullmatch(name)
            or not path.is_file()
            or path.stat().st_size > limit
        ):
            raise ValueError("Use --values ENV=LOCAL_FILE within RADEA_MAX_INPUT_BYTES")
        environments[name].append(path)
    return environments


def matrix(
    before: str, after: str, overrides: tuple[str, ...], limit: int,
    *, before_overrides: tuple[str, ...] = (), after_overrides: tuple[str, ...] = (),
) -> dict:
    charts = _local_chart(before), _local_chart(after)
    if len(overrides) + len(before_overrides) + len(after_overrides) > 40:
        raise ValueError("Use up to 40 total values overrides")
    shared, before_values, after_values = (
        _environment_values(items, limit)
        for items in (overrides, before_overrides, after_overrides)
    )
    names = shared.keys() | before_values.keys() | after_values.keys() or {"default"}
    if len(names) > 10:
        raise ValueError("Use up to 10 named environments")
    cases = []
    with TemporaryDirectory(prefix="radea-helm-") as directory:
        work = Path(directory)
        env = _environment(work)
        for name in sorted(names):
            before_render, after_render = work / "before.yaml", work / "after.yaml"
            for chart, output, values in zip(
                charts, (before_render, after_render), (before_values, after_values), strict=True,
            ):
                layers = [*shared.get(name, []), *values.get(name, [])]
                try:
                    _render(chart, layers, output, env, limit)
                except ValueError as error:
                    raise ValueError(f"{name}: {error}") from None
            changes = compare(str(before_render), str(after_render), limit, allow_empty=True)[
                "changes"
            ]
            cases.append({"environment": name, "changes": changes})
    return {"schema_version": "1.0", "command": "helm-matrix", "environments": cases}
