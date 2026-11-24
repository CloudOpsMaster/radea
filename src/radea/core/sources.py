"""Bounded, redacted evidence collection. Preserve source lines and log tails."""

import hashlib
import json
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

from radea.core.sanitizer import REDACT, sanitize


@dataclass
class Sources:
    records: dict[str, str] = field(default_factory=dict)
    files: list[dict] = field(default_factory=list)
    aliases: dict = field(default_factory=dict, repr=False)
    redactions: int = 0
    truncated: bool = False

    def add(self, path: str, *, budget: int, max_bytes: int) -> None:
        source = Path(path)
        if not source.is_file() or source.stat().st_size > max_bytes:
            raise ValueError("Input must be a regular file within RADEA_MAX_INPUT_BYTES")
        sid = f"s{len(self.files) + 1}"
        head: list[tuple[str, str]] = []
        tail: deque[tuple[str, str]] = deque()
        head_size = tail_size = total = read = 0
        digest = hashlib.sha256()
        pem = False
        clipped_lines = 0
        with source.open("rb") as stream:
            while raw := stream.readline(65537):
                read += len(raw)
                if read > max_bytes or len(raw) > 65536:
                    raise ValueError("Input exceeds byte or 64 KiB line limit")
                digest.update(raw)
                total += 1
                line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
                if "-----BEGIN " in line and "PRIVATE KEY-----" in line:
                    pem = True
                if pem:
                    self.redactions += 1
                    pem = "-----END " not in line
                    line = REDACT
                else:
                    result = sanitize(line, aliases=self.aliases)
                    self.redactions += result.redactions
                    line = result.text
                # Bound each line as well as total retained context.
                if len(line) > max(64, budget // 4):
                    clipped_lines += 1
                line = line[: max(64, budget // 4)]
                item = (f"{sid}:L{total}", line)
                size = len(line) + len(item[0]) + 12
                if head_size + size <= budget // 4:
                    head.append(item)
                    head_size += size
                else:
                    tail.append(item)
                    tail_size += size
                    while tail and tail_size > budget * 3 // 4:
                        old = tail.popleft()
                        tail_size -= len(old[0]) + len(old[1]) + 12
        retained = head + list(tail)
        self.records.update(retained)
        omitted = total - len(retained)
        self.truncated |= omitted > 0 or clipped_lines > 0
        self.files.append(
            {
                "id": sid,
                "name": sanitize(source.name).text,
                "sha256": digest.hexdigest(),
                "lines": total,
                "omitted_lines": omitted,
                "clipped_lines": clipped_lines,
            }
        )

    def payload(self) -> str:
        return json.dumps(
            {"sources": self.files, "evidence": self.records, "incomplete": self.truncated},
            ensure_ascii=False,
        )


def collect(paths: list[str], cfg) -> Sources:
    if not paths or len(paths) > 32:
        raise ValueError("Provide 1–32 source files")
    result = Sources()
    for path in paths:
        result.add(path, budget=cfg.max_log_chars // len(paths), max_bytes=cfg.max_input_bytes)
    return result
