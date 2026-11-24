"""CI configuration review for GitHub Actions and GitLab CI (articles 05, 31, 32, 34, 36, 38)."""

import re
from typing import Any

from radea.static_review.files import Source
from radea.static_review.findings import Finding, quote
from radea.static_review.yaml_loader import LDict, LList, Ref, get, line_of

SECRET_NAME = re.compile(r"(?i)password|passwd|secret|token|api[_-]?key|private[_-]?key|credential")
NOT_A_SECRET = re.compile(r"(?i)(?:_file|_path|_name|_enabled|_url|_ref|_dir|_type)$")
SECURITY_JOB = re.compile(
    r"(?i)scan|security|sast|dast|audit|lint|test|trivy|grype|codeql|snyk|verify|check|sbom|secret"
)
PIPE_TO_SHELL = re.compile(r"(?:curl|wget)\b[^|;&]*\|\s*(?:sudo\s+)?(?:ba|z|da|k)?sh\b")
ECHO_SECRET = re.compile(
    r"^\s*(?:echo|printf|cat)\b[^|>]*\$\{?[A-Za-z0-9_]*"
    r"(?:PASSWORD|PASSWD|SECRET|TOKEN|API_?KEY|PRIVATE_KEY|CREDENTIAL)",
    re.IGNORECASE,
)
ENV_DUMP = re.compile(r"^\s*(?:env|printenv|export\s+-p)\s*(?:\|.*)?$")
GH_ECHO_SECRET = re.compile(r"^\s*(?:echo|printf)\b[^|>]*\$\{\{\s*secrets\.", re.IGNORECASE)
GH_INJECTION = re.compile(
    r"\$\{\{[^}]*(?:github\.head_ref"
    r"|github\.event\.[\w.\[\]*-]*(?:title|body|message|label|name|email|ref|default_branch))"
    r"[^}]*\}\}",
    re.IGNORECASE,
)
UNTRUSTED_REF = re.compile(
    r"github\.event\.pull_request\.head|github\.head_ref|github\.event\.workflow_run\.head",
)
HELM_OTHER_VERBS = {
    "template", "lint", "repo", "show", "pull", "dependency", "plugin", "list", "status", "get",
    "history", "rollback", "uninstall", "test", "package", "push", "search", "env", "create",
    "verify",
}  # fmt: skip
FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
GL_RESERVED = {
    "stages", "variables", "default", "include", "workflow", "image", "services", "cache",
    "before_script", "after_script",
}  # fmt: skip
FLOATING_REFS = {"main", "master", "develop", "head", "latest", "~latest", "trunk"}


def _logical_lines(text: str) -> list[str]:
    """Join backslash continuations so flags on following lines belong to their command."""
    lines: list[str] = []
    buffer = ""
    for raw in text.splitlines() or [text]:
        stripped = raw.rstrip()
        if stripped.endswith("\\"):
            buffer += stripped[:-1].rstrip() + "\n"
            continue
        lines.append(buffer + raw)
        buffer = ""
    if buffer:
        lines.append(buffer)
    return lines


def _goes_elsewhere(rest: str) -> bool:
    """True when the echoed value is piped or redirected instead of printed to the job log."""
    if re.search(r"\|\s*tee\b", rest):
        return False
    return bool(re.search(r"\|\s*\S|>\s*\S", rest))


def find_line(src: Source, needle: str, start: int | None, window: int = 400) -> int | None:
    """Line of `needle` at or after `start`: block scalars hide their lines from the parser."""
    if start is None:
        return None
    wanted = needle.strip()
    for number in range(start, min(len(src.lines), start + window) + 1):
        if wanted and wanted in src.line(number):
            return number
    return start


def _texts(value: Any) -> list[str]:
    if isinstance(value, Ref):
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [t for item in value for t in _texts(item)]
    return []


def _image(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, dict) and isinstance(value.get("name"), str):
        return value["name"]
    return None


def _floating_image(image: str | None) -> bool:
    if not image or "$" in image or "{{" in image or "@sha256:" in image:
        return False
    last = image.rsplit("/", 1)[-1]
    tag = last.split(":", 1)[1] if ":" in last else None
    return tag in (None, "latest")


class _Ctx:
    def __init__(self, src: Source) -> None:
        self.src = src
        self.findings: list[Finding] = []

    def add(
        self,
        rule: str,
        target: str,
        line: int | None,
        detail: str = "",
        evidence: str | None = None,
    ) -> None:
        text = quote(self.src.line(line)) if evidence is None else evidence
        self.findings.append(Finding(rule, target, self.src.path, line, text, detail))

    def scripts(self, target: str, lines_of: Any, start: int | None, *, github: bool) -> None:
        """Run the shell-level rules over every logical line of every script block."""
        for text in _texts(lines_of):
            for raw in _logical_lines(text):
                line = (
                    find_line(self.src, raw.split("\n", 1)[0], start) if start is not None else None
                )
                self.script_line(target, raw.replace("\n", " "), line, github=github)

    def script_line(self, target: str, raw: str, line: int | None, *, github: bool) -> None:
        if PIPE_TO_SHELL.search(raw):
            self.add("CI005", target, line)
        secret_echo = (GH_ECHO_SECRET if github else ECHO_SECRET).search(raw)
        if secret_echo and _goes_elsewhere(raw[secret_echo.end() :]):
            secret_echo = None
        if secret_echo or ENV_DUMP.match(raw):
            self.add("CI006", target, line)
        if re.search(r"\bnpm install\b(?!\s+(?:-g|--global))", raw):
            self.add("CI012", target, line, "npm install")
        self.helm(target, raw, line)

    def helm(self, target: str, raw: str, line: int | None) -> None:
        for segment in re.split(r"&&|\|\||;|\|", raw):
            if not re.match(r"\s*(?:sudo\s+)?helm\b", segment):
                continue
            words = set(re.findall(r"(?<![\w-])[a-z][a-z-]*(?![\w-])", segment))
            if not words & {"upgrade", "install"} or words & HELM_OTHER_VERBS:
                continue
            if "--dry-run" in segment:
                continue
            missing = []
            if "--atomic" not in segment and "--rollback-on-failure" not in segment:
                missing.append("--atomic")
            if "--timeout" not in segment:
                missing.append("--timeout")
            if missing:
                self.add("CI013", target, line, "missing " + ", ".join(missing))


def review_ci(src: Source, documents: list[Any]) -> tuple[list[Finding], bool]:
    ctx = _Ctx(src)
    recognised = False
    for document in documents:
        if not isinstance(document, LDict):
            continue
        if isinstance(document.get("jobs"), LDict) and ("on" in document or True in document):
            recognised = True
            _github(ctx, document)
        elif _looks_like_gitlab(document):
            recognised = True
            _gitlab(ctx, document)
    return ctx.findings, recognised


def _looks_like_gitlab(document: LDict) -> bool:
    if any(key in document for key in ("stages", "include", "workflow")):
        return True
    return any(
        isinstance(v, dict) and ("script" in v or "trigger" in v)
        for k, v in document.items()
        if isinstance(k, str)
    )


# ---- GitHub Actions ---------------------------------------------------------------------------
def _triggers(document: LDict) -> set[str]:
    value = document.get("on", document.get(True))
    if isinstance(value, str):
        return {value}
    if isinstance(value, list):
        return {str(v) for v in value}
    return {str(k) for k in value} if isinstance(value, dict) else set()


def _github(ctx: _Ctx, document: LDict) -> None:
    jobs = document["jobs"]
    privileged = bool({"pull_request_target", "workflow_run"} & _triggers(document))
    top_permissions = document.get("permissions")
    if top_permissions == "write-all":
        ctx.add("CI003", "workflow", line_of(document, "permissions"), "write-all")
    elif top_permissions is None:
        loose = [
            str(j) for j, job in jobs.items() if isinstance(job, dict) and "permissions" not in job
        ]
        if loose:
            ctx.add("CI003", "workflow", line_of(document, "jobs"), "jobs: " + ", ".join(loose[:5]))
    for key in ("env",):
        _literal_secrets(ctx, "workflow", document.get(key))
    missing_timeout = []
    for job_id, job in jobs.items():
        if not isinstance(job, LDict):
            continue
        target = f"job {job_id}"
        if isinstance(job.get("uses"), str):
            _pin_action(ctx, target, job, job["uses"])
        elif "timeout-minutes" not in job:
            missing_timeout.append(str(job_id))
        for image in [_image(job.get("container"))] + [
            _image(s) for s in (get(job, "services") or {}).values()
        ]:
            if _floating_image(image):
                ctx.add("CI008", target, line_of(job, "container") or line_of(job), str(image))
        _literal_secrets(ctx, target, job.get("env"))
        if job.get("continue-on-error") is True and SECURITY_JOB.search(
            str(job.get("name", job_id))
        ):
            ctx.add("CI007", target, line_of(job, "continue-on-error"))
        for step in job.get("steps") or []:
            if isinstance(step, LDict):
                _github_step(ctx, target, step, privileged)
    if missing_timeout:
        ctx.add("CI011", "workflow", line_of(document, "jobs"), ", ".join(missing_timeout[:5]))


def _pin_action(ctx: _Ctx, target: str, node: LDict, uses: str) -> None:
    if uses.startswith("./") or "{{" in uses:
        return
    if uses.startswith("docker://"):
        if "@sha256:" not in uses:
            ctx.add("CI001", target, line_of(node, "uses"), uses)
        return
    ref = uses.split("@", 1)[1] if "@" in uses else ""
    if not FULL_SHA.match(ref):
        ctx.add("CI001", target, line_of(node, "uses"), uses)


def _github_step(ctx: _Ctx, target: str, step: LDict, privileged: bool) -> None:
    uses = step.get("uses")
    if isinstance(uses, str):
        _pin_action(ctx, target, step, uses)
        with_ref = str(get(step, "with", "ref") or "")
        if (
            privileged
            and uses.lower().startswith("actions/checkout")
            and UNTRUSTED_REF.search(with_ref)
        ):
            ctx.add("CI002", target, line_of(get(step, "with"), "ref"))
    name = str(step.get("name", uses or ""))
    if step.get("continue-on-error") is True and SECURITY_JOB.search(name):
        ctx.add("CI007", target, line_of(step, "continue-on-error"), name)
    _literal_secrets(ctx, target, step.get("env"))
    run = step.get("run")
    if isinstance(run, str):
        start = line_of(step, "run")
        for raw in run.splitlines():
            line = find_line(ctx.src, raw, start)
            if GH_INJECTION.search(raw):
                ctx.add("CI004", target, line)
        ctx.scripts(target, run, start, github=True)


def _literal_secrets(ctx: _Ctx, target: str, env: Any) -> None:
    if not isinstance(env, LDict):
        return
    for key, value in env.items():
        text = value.get("value") if isinstance(value, dict) else value
        if (
            isinstance(key, str)
            and SECRET_NAME.search(key)
            and not NOT_A_SECRET.search(key)
            and isinstance(text, (str, int))
            and str(text).strip()
            and "${{" not in str(text)
            and not str(text).startswith("$")
        ):
            ctx.add("CI009", target, line_of(env, key), key, evidence=f"{key}: value not shown")


# ---- GitLab CI --------------------------------------------------------------------------------
def _gitlab(ctx: _Ctx, document: LDict) -> None:
    _gitlab_includes(ctx, document)
    _literal_secrets(ctx, "variables", document.get("variables"))
    for key in ("image",):
        if _floating_image(_image(document.get(key))):
            ctx.add("CI008", "default", line_of(document, key), str(_image(document.get(key))))
    for key, job in document.items():
        if not isinstance(key, str) or key in GL_RESERVED or not isinstance(job, LDict):
            continue
        if not any(k in job for k in ("script", "extends", "trigger", "image", "stage")):
            continue
        target = f"job {key}"
        if _floating_image(_image(job.get("image"))):
            ctx.add("CI008", target, line_of(job, "image"), str(_image(job.get("image"))))
        for service in job.get("services") or []:
            if _floating_image(_image(service)):
                ctx.add("CI008", target, line_of(job, "services"), str(_image(service)))
        _literal_secrets(ctx, target, job.get("variables"))
        if ("only" in job or "except" in job) and "rules" not in job:
            ctx.add("CI010", target, line_of(job, "only" if "only" in job else "except"))
        allow = job.get("allow_failure")
        if allow is True and job.get("when") != "manual":
            label = f"{key} {job.get('stage', '')}"
            if SECURITY_JOB.search(label):
                ctx.add("CI007", target, line_of(job, "allow_failure"))
        for section in ("before_script", "script", "after_script"):
            block = job.get(section)
            if isinstance(block, LList):
                for index, entry in enumerate(block):
                    ctx.scripts(target, entry, block.item_line(index), github=False)
            elif isinstance(block, str):
                ctx.scripts(target, block, line_of(job, section), github=False)


def _gitlab_includes(ctx: _Ctx, document: LDict) -> None:
    include = document.get("include")
    entries = include if isinstance(include, list) else [include] if include else []
    for entry in entries:
        node = entry if isinstance(entry, LDict) else None
        line = line_of(node) if node is not None else line_of(document, "include")
        if isinstance(entry, str):
            if entry.startswith(("http://", "https://")):
                ctx.add("CI001", "include", line, "remote include")
            continue
        if node is None:
            continue
        if "remote" in node:
            ctx.add("CI001", "include", line_of(node, "remote"), "remote include")
        elif "project" in node:
            ref = str(node.get("ref", "")).lower()
            if not ref or ref in FLOATING_REFS:
                ctx.add(
                    "CI001", "include", line_of(node, "project"), f"project ref: {ref or 'none'}"
                )
        elif isinstance(node.get("component"), str):
            version = node["component"].split("@", 1)[1] if "@" in node["component"] else ""
            if not version or version.lower() in FLOATING_REFS:
                ctx.add(
                    "CI001",
                    "include",
                    line_of(node, "component"),
                    f"component @{version or 'none'}",
                )
