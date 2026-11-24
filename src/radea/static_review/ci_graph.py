"""Extract and compare local job dependencies from GitHub Actions and GitLab CI."""

from graphlib import CycleError, TopologicalSorter
from pathlib import Path
from typing import Any

from radea.core.sanitizer import clean
from radea.static_review.ci import GL_RESERVED
from radea.static_review.files import collect
from radea.static_review.yaml_loader import Ref, load_all

MAX_JOBS = 1000
DEFAULT_STAGES = (".pre", "build", "test", "deploy", ".post")
CONDITIONAL_KEYS = ("parallel", "rules", "only", "except", "trigger", "when")
GRAPH_KEYS = ("needs", "stage", *CONDITIONAL_KEYS)
MAX_EXTENDS_DEPTH = 11
WEB_PIPELINE_RULE = '$CI_PIPELINE_SOURCE == "web"'
_DIFF_METADATA = (
    "platform", "source", "unresolved_needs", "unresolved_extends", "resolved_local_includes",
)


def _names(value: Any, field: str) -> list[str]:
    if isinstance(value, Ref) or not isinstance(value, list):
        raise ValueError(f"{field} must be a literal list")
    if not all(isinstance(item, str) and item.strip() for item in value):
        raise ValueError(f"{field} must contain nonempty strings")
    return value


def _gitlab_needs(value: Any) -> tuple[set[str], set[str], bool]:
    if isinstance(value, Ref) or not isinstance(value, list):
        raise ValueError("GitLab needs must be a literal list")
    required: set[str] = set()
    optional: set[str] = set()
    external = False
    for item in value:
        if isinstance(item, str) and item.strip():
            required.add(item)
            continue
        if not isinstance(item, dict):
            raise ValueError("Invalid GitLab needs entry")
        if "project" in item or "pipeline" in item:
            external = True
            continue
        name = item.get("job")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("GitLab needs entry requires a job name")
        target = optional if item.get("optional") is True else required
        target.add(name)
    return required, optional - required, external


def _mapping(text: str) -> dict:
    docs = load_all(text, strict=True)
    if len(docs) != 1 or not isinstance(docs[0], dict):
        raise ValueError("Expected one pipeline YAML mapping")
    return docs[0]


def _merge(old: dict, new: dict) -> dict:
    result = dict(old)
    for key, item in new.items():
        previous = result.get(key)
        result[key] = (
            _merge(previous, item)
            if isinstance(previous, dict) and isinstance(item, dict)
            else item
        )
    return result


def _local_includes(path: str, root_path: str, config: dict, bytes_left: int) -> tuple[dict, int]:
    root = Path(root_path).resolve()
    entry = Path(path).resolve()
    if path == "-" or not root.is_dir() or not entry.is_relative_to(root):
        raise ValueError("Local includes require a pipeline file inside the supplied GitLab root")
    count = 0

    def expand(document: dict, ancestry: tuple[Path, ...]) -> dict:
        nonlocal bytes_left, count
        entries = document.get("include", [])
        if not isinstance(entries, list):
            entries = [entries]
        if len(entries) > 32 or len(ancestry) > 12:
            raise ValueError("GitLab include structure exceeds supported limits")
        merged: dict = {}
        unresolved = []
        for include in entries:
            local = include if isinstance(include, str) else None
            if isinstance(include, dict) and set(include) == {"local"}:
                local = include["local"]
            if (
                not isinstance(local, str)
                or not local
                or any(special in local for special in (":", "$", "*", "?", "[", chr(92), chr(0)))
            ):
                unresolved.append(include)
                continue
            requested = Path(local.lstrip("/"))
            target = (root / requested).resolve()
            if ".." in requested.parts or not target.is_relative_to(root):
                raise ValueError("Local GitLab include escapes the repository root")
            if target in ancestry:
                raise ValueError("GitLab local include cycle")
            if count >= 32 or bytes_left <= 0:
                raise ValueError("GitLab local includes exceed supported limits")
            if not target.is_file():
                raise ValueError("Expected a local GitLab include file")
            sources, _ = collect([str(target)], max_bytes=bytes_left)
            if len(sources) != 1:
                raise ValueError("Cannot read a local GitLab include within the byte limit")
            text = sources[0].text
            bytes_left -= len(text.encode())
            count += 1
            included = expand(_mapping(text), (*ancestry, target))
            unresolved.extend(included.pop("include", []))
            merged = _merge(merged, included)
        merged = _merge(merged, {key: value for key, value in document.items() if key != "include"})
        if unresolved:
            merged["include"] = unresolved
        return merged

    return expand(config, (entry,)), count


def _graph(path: str, max_bytes: int, platform: str, gitlab_root: str | None = None) -> dict:
    sources, _ = collect([path], max_bytes=max_bytes)
    if len(sources) != 1:
        raise ValueError("Expected one pipeline file")
    source = sources[0]
    config = _mapping(source.text)
    metadata = {}
    if gitlab_root is not None:
        if platform == "github" or (
            platform == "auto"
            and isinstance(config.get("jobs"), dict)
            and (True in config or "on" in config)
        ):
            raise ValueError("--gitlab-root requires a GitLab pipeline")
        config, count = _local_includes(
            path, gitlab_root, config, max_bytes - len(source.text.encode())
        )
        platform = "gitlab"
        metadata = {"resolved_local_includes": count}
    return {**build_graph(config, platform), "source": source.meta(), **metadata}


def _inherit_graph_keys(
    definitions: dict[str, dict], jobs: dict[str, dict],
) -> tuple[dict[str, dict], set[str]]:
    cache: dict[str, tuple[dict, int]] = {}
    unresolved: set[str] = set()

    def resolve(name: str, ancestry: tuple[str, ...]) -> tuple[dict, int]:
        if name in ancestry:
            raise ValueError("GitLab extends contains an inheritance cycle")
        if len(ancestry) > MAX_EXTENDS_DEPTH:
            raise ValueError("GitLab extends exceeds eleven inheritance levels")
        if name in cache:
            cached_fields, cached_depth = cache[name]
            if len(ancestry) + cached_depth > MAX_EXTENDS_DEPTH:
                raise ValueError("GitLab extends exceeds eleven inheritance levels")
            return cached_fields, cached_depth
        definition = definitions.get(name)
        if definition is None:
            unresolved.add(name)
            return {}, 0
        value = definition.get("extends", [])
        parents = _names([value] if isinstance(value, str) else value, "extends")
        if len(parents) > 32:
            raise ValueError("GitLab extends exceeds 32 parents per job")
        effective: dict = {}
        depth = 0
        # Graph fields are whole values. The last parent wins, then the child wins.
        for parent in parents:
            inherited, parent_depth = resolve(parent, (*ancestry, name))
            effective.update(inherited)
            depth = max(depth, parent_depth + 1)
        effective.update({key: definition[key] for key in GRAPH_KEYS if key in definition})
        cache[name] = effective, depth
        return effective, depth

    return {name: resolve(name, ())[0] for name in jobs}, unresolved


def build_graph(config: dict, platform: str) -> dict:
    unresolved_extends: set[str] = set()
    if platform == "auto":
        platform = (
            "github"
            if isinstance(config.get("jobs"), dict) and (True in config or "on" in config)
            else "gitlab"
        )
    if platform == "github":
        jobs = config.get("jobs")
        if not isinstance(jobs, dict):
            raise ValueError("GitHub Actions workflow requires a jobs mapping")
        stages: list[str] = []
    else:
        definitions = {
            name: job
            for name, job in config.items()
            if isinstance(name, str)
            and name not in GL_RESERVED
            and name != "spec"
            and isinstance(job, dict)
        }
        if len(definitions) > MAX_JOBS:
            raise ValueError(f"Expected at most {MAX_JOBS} GitLab jobs and templates")
        jobs = {name: job for name, job in definitions.items() if not name.startswith(".")}
        jobs, unresolved_extends = _inherit_graph_keys(definitions, jobs)
        stages = _names(config.get("stages", list(DEFAULT_STAGES)), "stages")
        stages = [".pre", *(stage for stage in stages if stage not in {".pre", ".post"}), ".post"]
    if not jobs or len(jobs) > MAX_JOBS:
        raise ValueError(f"Expected between 1 and {MAX_JOBS} jobs")
    if not all(isinstance(name, str) and isinstance(job, dict) for name, job in jobs.items()):
        raise ValueError("Expected named job mappings")

    position = {stage: index for index, stage in enumerate(stages)}
    stage_of: dict[str, str] = {}
    if platform == "gitlab":
        for name, job in jobs.items():
            stage = job.get("stage", "test")
            if not isinstance(stage, str) or stage not in position:
                raise ValueError("GitLab job stage is absent from stages")
            stage_of[name] = stage

    dependencies: dict[str, set[str]] = {}
    result = []
    unresolved: set[str] = set()
    edge_count = 0
    incomplete = platform == "gitlab" and (
        bool(unresolved_extends)
        or "include" in config
        or (
            "workflow" in config
            and config["workflow"] != {"rules": [{"if": WEB_PIPELINE_RULE}]}
        )
    )
    for name, job in sorted(jobs.items()):
        optional: set[str] = set()
        if platform == "github":
            value = job.get("needs", [])
            required = set(_names([value] if isinstance(value, str) else value, "needs"))
            mode = "explicit"
            incomplete |= "uses" in job or "strategy" in job or "if" in job
        elif "needs" in job:
            required, optional, external = _gitlab_needs(job["needs"])
            mode = "explicit"
            incomplete |= external
        else:
            stage_index = position[stage_of[name]]
            required = {job for job, stage in stage_of.items() if position[stage] < stage_index}
            mode = "stage"
        if platform == "gitlab":
            incomplete |= any(key in job for key in CONDITIONAL_KEYS)
        edge_count += len(required) + len(optional)
        if edge_count > 50_000:
            raise ValueError("Pipeline graph exceeds 50000 dependency edges")
        unresolved.update(required - jobs.keys())
        dependencies[name] = (required | optional) & jobs.keys()
        result.append(
            {
                "name": name,
                "stage": stage_of.get(name),
                "mode": mode,
                "needs": sorted(required),
                "optional_needs": sorted(optional),
            }
        )
    try:
        order = list(
            TopologicalSorter(
                {name: sorted(edges) for name, edges in dependencies.items()}
            ).static_order()
        )
    except CycleError:
        raise ValueError("Pipeline contains a local dependency cycle") from None
    return {
        "platform": platform,
        "jobs": result,
        "order": order,
        "unresolved_needs": sorted(unresolved),
        "partial": bool(incomplete or unresolved),
        **({"unresolved_extends": sorted(unresolved_extends)} if platform == "gitlab" else {}),
    }


def graph(path: str, max_bytes: int, platform: str, gitlab_root: str | None = None) -> dict:
    return clean({"schema_version": "1.0", **_graph(path, max_bytes, platform, gitlab_root)})


def compare(
    before: str, after: str, max_bytes: int, before_platform: str, after_platform: str,
    *, before_gitlab_root: str | None = None, after_gitlab_root: str | None = None,
) -> dict:
    if before == after == "-":
        raise ValueError("Only one pipeline may use stdin")
    previous = _graph(before, max_bytes, before_platform, before_gitlab_root)
    current = _graph(after, max_bytes, after_platform, after_gitlab_root)
    old = {job["name"]: job for job in previous["jobs"]}
    new = {job["name"]: job for job in current["jobs"]}
    modified = [
        {"name": name, "before": old[name], "after": new[name]}
        for name in sorted(old.keys() & new.keys())
        if any(old[name][key] != new[name][key] for key in ("needs", "optional_needs"))
    ]
    return clean(
        {
            "schema_version": "1.0",
            "before": {key: previous[key] for key in _DIFF_METADATA if key in previous},
            "after": {key: current[key] for key in _DIFF_METADATA if key in current},
            "added": sorted(new.keys() - old.keys()),
            "removed": sorted(old.keys() - new.keys()),
            "modified": modified,
            "partial": previous["partial"] or current["partial"],
        }
    )
