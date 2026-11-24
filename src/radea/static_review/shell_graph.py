"""Trace literal shell file references from a parsed script without running it."""

import json
import re
import subprocess
from collections import deque
from pathlib import Path
from tempfile import TemporaryFile
from typing import Any

from radea.core.sanitizer import clean
from radea.static_review.files import collect
from radea.static_review.yaml_loader import get

PATH_WORD = re.compile(r"[A-Za-z0-9_./ -]{1,512}\Z")
SHELLS = {"bash", "dash", "ksh", "sh", "zsh"}
DYNAMIC = {"cd", "pushd", "popd", "eval"}
MAX_FILES = 24
MAX_SCRIPT_BYTES = 65_536
MAX_AST_BYTES = 8 * 1024 * 1024


def _literal(word: Any) -> str | None:
    parts = get(word, "Parts")
    if not isinstance(parts, list) or len(parts) != 1:
        return None
    part = parts[0]
    kind = get(part, "Type")
    if kind == "DblQuoted" and not get(part, "Dollar"):
        children = get(part, "Parts")
        if not isinstance(children, list) or len(children) != 1:
            return None
        part = children[0]
        kind = get(part, "Type")
    if kind not in {"Lit", "SglQuoted"} or get(part, "Dollar"):
        return None
    value = get(part, "Value")
    return value if isinstance(value, str) and PATH_WORD.fullmatch(value) else None


def _commands(text: str, dialect: str) -> list[tuple[int, str, str | None]]:
    with TemporaryFile() as output:
        try:
            result = subprocess.run(
                ["shfmt", "--to-json", f"-ln={dialect}"], input=text.encode(),
                stdout=output, stderr=subprocess.DEVNULL, timeout=10, check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            raise ValueError("shfmt is unavailable or could not finish parsing") from None
        if result.returncode:
            raise ValueError("shfmt could not parse the script")
        output.seek(0)
        data = output.read(MAX_AST_BYTES + 1)
    if len(data) > MAX_AST_BYTES:
        raise ValueError("Shell syntax tree exceeds the supported byte limit")
    try:
        tree = json.loads(data)
    except (ValueError, RecursionError):
        raise ValueError("Invalid shfmt syntax tree") from None
    if get(tree, "Type") != "File":
        raise ValueError("Unsupported shfmt syntax tree")

    commands = []
    stack = [tree]
    while stack:
        node = stack.pop()
        if isinstance(node, list):
            stack.extend(reversed(node))
        elif isinstance(node, dict):
            stack.extend(reversed(list(node.values())))
            if node.get("Type") != "CallExpr":
                continue
            line = get(node, "Pos", "Line")
            action = _literal(get(node, "Args", 0))
            if type(line) is not int or action is None:
                continue
            if action in {"source", "."} | SHELLS:
                commands.append((line, action, _literal(get(node, "Args", 1))))
            elif action in DYNAMIC:
                commands.append((line, action, None))
            elif action.startswith(("./", "../")) and action.endswith(".sh"):
                commands.append((line, "direct", action))
    return sorted(commands, key=lambda item: item[0])


def graph(path: str, root_path: str, dialect: str, limit: int) -> dict:
    root = Path(root_path).resolve()
    entry = Path(path).resolve()
    if not root.is_dir() or not entry.is_relative_to(root):
        raise ValueError("The entry script must be inside the specified repository root")
    pending = deque([entry])
    seen = {entry}
    sources = []
    references = []
    remaining = limit
    while pending:
        if remaining <= 0:
            raise ValueError("Shell graph exceeds the input byte limit")
        script = pending.popleft()
        relative = script.relative_to(root).as_posix()
        units, _ = collect([str(script)], max_bytes=min(remaining, MAX_SCRIPT_BYTES))
        source = units[0]
        remaining -= len(source.text.encode())
        sources.append({**source.meta(), "path": relative})
        for line, action, target in _commands(source.text, dialect):
            reason = None
            resolved = None
            if target is None or target.startswith("-"):
                reason = (
                    "working_directory_or_eval" if action in DYNAMIC else "dynamic_or_unsupported"
                )
            elif action in {"source", "."} and "/" not in target:
                reason = "shell_path_lookup"
            elif Path(target).is_absolute():
                reason = "outside_root"
            else:
                candidate = (root / target).resolve()
                if not candidate.is_relative_to(root):
                    reason = "outside_root"
                elif not candidate.is_file():
                    reason = "missing_file"
                elif candidate not in seen and len(seen) >= MAX_FILES:
                    reason = "file_limit"
                else:
                    resolved = candidate.relative_to(root).as_posix()
                    if candidate not in seen:
                        seen.add(candidate)
                        pending.append(candidate)
            references.append({
                "script": relative, "line": line, "action": action,
                "target": resolved, "unresolved": reason,
            })
    return clean({
        "schema_version": "1.0", "command": "shell-graph", "sources": sources,
        "references": references, "partial": any(ref["unresolved"] for ref in references),
    })
