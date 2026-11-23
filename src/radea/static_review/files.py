"""Bounded, symlink-safe collection of the files a static review reads."""

import hashlib
import os
import sys
from dataclasses import dataclass
from pathlib import Path

SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", ".tox", ".mypy_cache"}
MAX_FILES = 500


@dataclass(frozen=True)
class Source:
    path: str
    text: str
    sha256: str
    lines: tuple[str, ...]

    def line(self, number: int | None) -> str:
        if number is None or not 1 <= number <= len(self.lines):
            return ""
        return self.lines[number - 1]

    def meta(self) -> dict:
        return {
            "path": self.path,
            "sha256": self.sha256,
            "lines": len(self.lines),
            "bytes": len(self.text.encode()),
        }


def _read(path: str, data: bytes) -> Source:
    text = data.decode("utf-8", errors="replace")
    return Source(path, text, hashlib.sha256(data).hexdigest(), tuple(text.splitlines()))


def collect(
    paths: tuple[str, ...] | list[str],
    *,
    suffixes: tuple[str, ...] = (),
    names: tuple[str, ...] = (),
    max_bytes: int,
) -> tuple[list[Source], list[dict]]:
    """Return (sources, skipped). Explicit file arguments must be readable; walked files that
    are too large are skipped and reported rather than silently ignored."""
    sources: list[Source] = []
    skipped: list[dict] = []
    seen: set[str] = set()

    def matches(name: str) -> bool:
        lowered = name.lower()
        return lowered in names or lowered.endswith(suffixes) or name.startswith(names)

    def take(path: Path, explicit: bool) -> None:
        key = str(path)
        if key in seen:
            return
        seen.add(key)
        if len(sources) >= MAX_FILES:
            skipped.append({"path": key, "reason": f"more than {MAX_FILES} files"})
            return
        if path.is_symlink() and not explicit:
            skipped.append({"path": key, "reason": "symlink not followed"})
            return
        if not path.is_file():
            raise ValueError(f"Not a regular file: {key}")
        if path.stat().st_size > max_bytes:
            if explicit:
                raise ValueError("Input must be a regular file within RADEA_MAX_INPUT_BYTES")
            skipped.append({"path": key, "reason": "larger than RADEA_MAX_INPUT_BYTES"})
            return
        sources.append(_read(key, path.read_bytes()))

    for raw in paths:
        if raw == "-":
            data = sys.stdin.buffer.read(max_bytes + 1)
            if len(data) > max_bytes:
                raise ValueError("Input must be within RADEA_MAX_INPUT_BYTES")
            sources.append(_read("<stdin>", data))
            continue
        path = Path(raw)
        if path.is_dir():
            for root, dirs, files in os.walk(path, followlinks=False):
                dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
                for name in sorted(files):
                    if matches(name):
                        take(Path(root) / name, explicit=False)
        else:
            take(path, explicit=True)
    return sources, skipped
