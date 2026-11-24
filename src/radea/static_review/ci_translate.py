"""Translate simple shell jobs into manual GitHub Actions or GitLab CI drafts."""

import re

from radea.static_review.ci import GL_RESERVED
from radea.static_review.ci_graph import WEB_PIPELINE_RULE, build_graph
from radea.static_review.files import collect
from radea.static_review.yaml_loader import load_all

JOB_ID = re.compile(r"[A-Za-z_][A-Za-z0-9_-]{0,99}\Z")
FOREIGN_CONTEXT = re.compile(r"\${\{|\$\{?(?:CI(?:_|\b)|GITLAB_|FF_)")
GITHUB_CONTEXT = re.compile(r"\${\{|\$\{?(?:GITHUB_|RUNNER_|ACTIONS_)")
PINNED_IMAGE = re.compile(r"[A-Za-z0-9][A-Za-z0-9./:_-]{0,180}@sha256:[0-9a-f]{64}\Z")
CHECKOUT = "actions/checkout@11d5960a326750d5838078e36cf38b85af677262"


def _config(path: str, max_bytes: int, platform: str) -> dict:
    sources, _ = collect([path], max_bytes=max_bytes)
    if len(sources) != 1:
        raise ValueError(f"Expected one {platform} CI file")
    docs = load_all(sources[0].text, strict=True)
    if len(docs) != 1 or not isinstance(docs[0], dict):
        raise ValueError(f"Expected one {platform} CI YAML mapping")
    return docs[0]


def translate(path: str, max_bytes: int) -> dict:
    config = _config(path, max_bytes, "GitLab")
    jobs: dict[str, dict] = {}
    for name, definition in config.items():
        if name == "stages":
            continue
        if (
            not isinstance(name, str)
            or not JOB_ID.fullmatch(name)
            or name in GL_RESERVED
            or name == "spec"
            or not isinstance(definition, dict)
        ):
            raise ValueError("Only stages and named GitLab jobs can be translated")
        if set(definition) - {"stage", "script", "needs"}:
            raise ValueError("Unsupported job fields; supported fields are stage, script and needs")
        script = definition.get("script")
        needs = definition.get("needs", [])
        if not isinstance(needs, list) or not all(isinstance(item, str) for item in needs):
            raise ValueError("Translation supports only plain local needs entries")
        if (
            not isinstance(script, list)
            or not script
            or not all(isinstance(line, str) for line in script)
        ):
            raise ValueError("Each job requires a nonempty script list of strings")
        commands = "\n".join(script)
        if not commands.strip() or len(commands) > 20_000 or FOREIGN_CONTEXT.search(commands):
            raise ValueError("Script is empty, too large or uses a platform-specific expression")
        jobs[name] = {"commands": commands}
    topology = build_graph(config, "gitlab")
    if topology["partial"]:
        raise ValueError("Pipeline has unresolved or externally defined dependencies")
    result = {}
    for job in topology["jobs"]:
        name = job["name"]
        output = {
            "runs-on": "ubuntu-24.04",
            "timeout-minutes": 30,
            "steps": [
                {"uses": CHECKOUT, "with": {"persist-credentials": False}},
                {"shell": "bash", "run": jobs[name]["commands"]},
            ],
        }
        if job["needs"]:
            output["needs"] = job["needs"]
        result[name] = output
    return {
        "name": "Migrated pipeline draft",
        "on": {"workflow_dispatch": {}},
        "permissions": {"contents": "read"},
        "jobs": result,
    }


def translate_github(path: str, image: str, max_bytes: int) -> dict:
    if not PINNED_IMAGE.fullmatch(image):
        raise ValueError("GitLab draft requires a container image pinned by SHA-256")
    config = _config(path, max_bytes, "GitHub Actions")
    if set(config) - {"name", "on", "permissions", "jobs"}:
        raise ValueError("Unsupported GitHub Actions workflow fields")
    topology = build_graph(config, "github")
    if topology["partial"]:
        raise ValueError("Pipeline has unresolved or conditional dependencies")
    draft: dict = {"workflow": {"rules": [{"if": WEB_PIPELINE_RULE}]}, "stages": ["jobs"]}
    for job in topology["jobs"]:
        name, dependencies = job["name"], job["needs"]
        definition = config["jobs"][name]
        if (
            not JOB_ID.fullmatch(name) or name in GL_RESERVED or name == "spec"
            or set(definition) - {"name", "runs-on", "timeout-minutes", "needs", "steps"}
            or definition.get("runs-on") not in ("ubuntu-22.04", "ubuntu-24.04", "ubuntu-latest")
            or len(dependencies) > 50
        ):
            raise ValueError("Only simple named Ubuntu jobs with up to 50 needs can be translated")
        steps = definition.get("steps")
        if not isinstance(steps, list):
            raise ValueError("Expected a checkout step and one Bash step")
        if len(steps) != 2 or steps[0] != {
            "uses": CHECKOUT, "with": {"persist-credentials": False},
        }:
            raise ValueError("Expected supported pinned checkout and one Bash step")
        step = steps[1]
        if (
            not isinstance(step, dict)
            or set(step) - {"name", "shell", "run"}
            or step.get("shell") != "bash"
        ):
            raise ValueError("Expected one explicit Bash run step")
        script = step.get("run")
        if (
            not isinstance(script, str) or not script.strip() or len(script) > 20_000
            or GITHUB_CONTEXT.search(script) or FOREIGN_CONTEXT.search(script)
        ):
            raise ValueError("Script is empty, too large or uses a GitHub-specific expression")
        translated = {
            "stage": "jobs",
            "image": image,
            "needs": [{"job": dependency, "artifacts": False} for dependency in dependencies],
            "script": ["set -eo pipefail\n" + script],
        }
        if "timeout-minutes" in definition:
            minutes = definition["timeout-minutes"]
            if type(minutes) is not int or not 1 <= minutes <= 360:
                raise ValueError("Job timeout must be an integer from 1 to 360 minutes")
            translated["timeout"] = f"{minutes} minutes"
        draft[name] = translated
    return draft
