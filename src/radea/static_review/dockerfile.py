"""Dockerfile review (articles 12, 34, 38, 65, 66, 69). Line-based parser, no build."""

import re
from dataclasses import dataclass

from radea.static_review.files import Source
from radea.static_review.findings import Finding, quote

SECRET_NAME = re.compile(r"(?i)password|passwd|secret|token|api[_-]?key|private[_-]?key|credential")
NOT_A_SECRET = re.compile(r"(?i)(?:_file|_path|_name|_enabled|_url|_ref|_dir)$")
SECRET_FILE = re.compile(
    r"(?i)(?:^|[/\s])(?:id_rsa|id_ed25519|id_ecdsa|\.env|\.netrc|\.npmrc|\.pypirc|\.git-credentials"
    r"|credentials(?:\.json)?|[^/\s]+\.(?:pem|key|p12|pfx|jks|keystore))(?:\s|$)"
)
PIPE_TO_SHELL = re.compile(r"(?:curl|wget)\b[^|;&]*\|\s*(?:sudo\s+)?(?:ba|z|da|k)?sh\b")
BUILD_TOOLS = re.compile(
    r"\b(?:build-essential|gcc|g\+\+|cmake|maven|mvn|gradle|go build|cargo build|dotnet publish"
    r"|npm run build|yarn build|javac)\b|\bmake\b(?!\s*(?:-p|dir))"
)
INSTALL_DEPS = re.compile(
    r"\b(?:pip3? install|npm (?:ci|install)|yarn install|mvn|gradle|go mod download|bundle install"
    r"|composer install|dotnet restore)\b"
)


@dataclass
class Instruction:
    name: str
    args: str
    line: int  # 1-based line where the instruction starts


def parse(text: str) -> list[Instruction]:
    instructions: list[Instruction] = []
    buffer, start = "", 0
    for number, raw in enumerate(text.splitlines(), 1):
        stripped = raw.strip()
        if not buffer and (not stripped or stripped.startswith("#")):
            continue
        if not buffer:
            start = number
        if stripped.startswith("#"):
            continue
        if stripped.endswith("\\"):
            buffer += stripped[:-1] + " "
            continue
        buffer += stripped
        name, _, args = buffer.partition(" ")
        instructions.append(Instruction(name.upper(), args.strip(), start))
        buffer = ""
    if buffer:
        name, _, args = buffer.partition(" ")
        instructions.append(Instruction(name.upper(), args.strip(), start))
    return instructions


def _split_image(args: str) -> tuple[str, str | None, bool, str | None]:
    """(image, tag, has_digest, stage_alias) from the arguments of FROM."""
    tokens = [t for t in args.split() if not t.startswith("--")]
    image = tokens[0] if tokens else ""
    alias = tokens[2] if len(tokens) >= 3 and tokens[1].lower() == "as" else None
    digest = "@sha256:" in image
    base = image.split("@", 1)[0]
    last = base.rsplit("/", 1)[-1]
    tag = last.split(":", 1)[1] if ":" in last else None
    return base, tag, digest, alias


def review_dockerfile(src: Source) -> list[Finding]:
    findings: list[Finding] = []
    instructions = parse(src.text)

    def emit(rule: str, target: str, ins: Instruction, detail: str = "", evidence=None) -> None:
        text = quote(src.line(ins.line)) if evidence is None else evidence
        findings.append(Finding(rule, target, src.path, ins.line, text, detail))

    stages: list[list[Instruction]] = []
    aliases: set[str] = set()
    for ins in instructions:
        if ins.name == "FROM":
            stages.append([])
        if stages:
            stages[-1].append(ins)
    if not stages:
        return findings

    for number, stage in enumerate(stages, 1):
        head = stage[0]
        target = f"stage {number}"
        image, tag, digest, alias = _split_image(head.args)
        if alias:
            target = f"stage {alias}"
        skip = not image or image == "scratch" or "$" in image or image.lower() in aliases
        if alias:
            aliases.add(alias.lower())
        if not skip:
            if tag in (None, "latest") and not digest:
                emit("DF001", target, head, image)
            elif not digest:
                emit("DF009", target, head, image)
        _review_stage(stage, target, number == len(stages), len(stages), emit)
    return findings


def _review_stage(stage, target, is_final, stage_count, emit) -> None:
    user = None
    copied_all: Instruction | None = None
    for ins in stage:
        args = ins.args
        if ins.name == "USER":
            user = (ins, args.split(":")[0].strip())
        elif ins.name in {"ENV", "ARG"}:
            _secret_in_variable(ins, target, emit)
        elif ins.name in {"COPY", "ADD"}:
            if SECRET_FILE.search(" " + re.sub(r"--\S+\s*", "", args)):
                emit("DF003", target, ins, "secret-like file copied into the image")
            if ins.name == "ADD" and re.match(r"(?:--\S+\s+)*https?://", args):
                emit("DF004", target, ins, "ADD from a URL")
            sources = re.sub(r"--\S+\s*", "", args).split()
            if copied_all is None and sources and sources[0] in {".", "./"}:
                copied_all = ins
        elif ins.name == "RUN":
            _review_run(ins, target, copied_all, stage_count, emit)
            if copied_all is not None and INSTALL_DEPS.search(args):
                emit("DF007", target, copied_all)
                copied_all = None
    if is_final:
        head = stage[0]
        if user is None:
            emit("DF002", target, head, "no USER instruction")
        elif user[1].lower() in {"root", "0"}:
            emit("DF002", target, user[0], "last USER is root")


def _secret_in_variable(ins, target, emit) -> None:
    pairs = re.findall(r"([A-Za-z_][A-Za-z0-9_]*)(?:=(\S*))?", ins.args)
    if ins.name == "ENV" and "=" not in ins.args:
        key, _, value = ins.args.partition(" ")
        pairs = [(key, value.strip())]
    for key, value in pairs[:20]:
        if SECRET_NAME.search(key) and not NOT_A_SECRET.search(key):
            if ins.name == "ENV" and not value:
                continue
            kind = "ENV" if ins.name == "ENV" else "ARG"
            emit("DF003", target, ins, f"{kind} {key}", evidence=f"{kind} {key}: value not shown")


def _review_run(ins, target, copied_all, stage_count, emit) -> None:
    args = ins.args
    if PIPE_TO_SHELL.search(args):
        emit("DF004", target, ins, "download piped to a shell")
    if re.search(r"chmod\s+(?:-R\s+)?(?:0?777|a\+rwx)|\bsudo\b", args):
        emit("DF008", target, ins)
    problems = []
    if re.search(r"apt(?:-get)?\s+install", args):
        if "--no-install-recommends" not in args:
            problems.append("apt without --no-install-recommends")
        if "/var/lib/apt/lists" not in args:
            problems.append("apt lists not removed")
    if re.search(r"\bapk\s+add", args) and "--no-cache" not in args:
        problems.append("apk add without --no-cache")
    if re.search(r"\bpip3?\s+install", args) and "--no-cache-dir" not in args:
        problems.append("pip without --no-cache-dir")
    if re.search(r"\b(?:yum|dnf)\s+install", args) and "clean all" not in args:
        problems.append("yum/dnf cache not cleaned")
    if problems:
        emit("DF005", target, ins, "; ".join(problems))
    if stage_count == 1 and BUILD_TOOLS.search(args):
        emit("DF006", target, ins)
