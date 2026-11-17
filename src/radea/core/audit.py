"""Private append-only metadata events, with no prompts, responses or credentials."""

import json
import os
from datetime import datetime, timezone
from pathlib import Path


def write(cfg, event: dict) -> None:
    if not cfg.audit:
        return
    directory = Path(cfg.audit_dir)
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if directory.is_symlink():
        raise ValueError("Audit directory cannot be a symlink")
    path = directory / "audit.jsonl"
    flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        row = {"at": datetime.now(timezone.utc).isoformat(), **event}
        encoded = (json.dumps(row, sort_keys=True) + "\n").encode()
        if os.write(descriptor, encoded) != len(encoded):
            raise OSError("Incomplete audit record")
    finally:
        os.close(descriptor)
