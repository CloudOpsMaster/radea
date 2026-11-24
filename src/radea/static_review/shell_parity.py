"""Compare trusted baseline and replacement shell scripts against shared cases."""

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

from radea.static_review.files import collect

CASE_ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}\Z")


def _run(script: str, args: list[str], stdin: str, interpreter: str, limit: int) -> tuple:
    with TemporaryDirectory(prefix="radea-shell-case-") as directory:
        work = Path(directory)
        executable = work / "script"
        executable.write_text(script)
        env = {"PATH": os.defpath, "HOME": directory, "TMPDIR": directory, "LC_ALL": "C"}
        with (work / "stdout").open("w+b") as stdout, (work / "stderr").open("w+b") as stderr:
            try:
                result = subprocess.run(
                    [interpreter, str(executable), *args],
                    input=stdin.encode(),
                    stdout=stdout,
                    stderr=stderr,
                    cwd=work,
                    env=env,
                    timeout=5,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                raise ValueError("A shell case timed out") from None
            streams = []
            for stream in (stdout, stderr):
                stream.seek(0)
                output = stream.read(limit + 1)
                if len(output) > limit:
                    raise ValueError("A shell case exceeded the output byte limit")
                streams.append(hashlib.sha256(output).digest())
            return result.returncode, *streams


def compare(baseline: str, candidate: str, spec: str, interpreter: str, limit: int) -> dict:
    sources = []
    for path in (baseline, candidate, spec):
        files, _ = collect([path], max_bytes=limit)
        if len(files) != 1:
            raise ValueError("Expected two local scripts and a JSON case file")
        sources.append(files[0].text)
    try:
        cases = json.loads(sources[2])
    except (ValueError, RecursionError):
        raise ValueError("Invalid shell case JSON") from None
    if not isinstance(cases, list) or not 1 <= len(cases) <= 20:
        raise ValueError("Supply between 1 and 20 shell cases")
    parsed = []
    seen = set()
    for case in cases:
        if not isinstance(case, dict):
            raise ValueError("Each shell case requires an id, args and optional stdin")
        key, args, stdin = case.get("id"), case.get("args"), case.get("stdin", "")
        if (
            not isinstance(key, str)
            or not CASE_ID.fullmatch(key)
            or key in seen
            or not isinstance(args, list)
            or len(args) > 32
            or any(not isinstance(arg, str) or len(arg) > 4096 or "\0" in arg for arg in args)
            or not isinstance(stdin, str)
            or len(stdin.encode()) > limit
        ):
            raise ValueError("Invalid or duplicate shell case")
        parsed.append((key, args, stdin))
        seen.add(key)
    reports = []
    for key, args, stdin in parsed:
        before, after = (_run(source, args, stdin, interpreter, limit) for source in sources[:2])
        differences = [
            name
            for name, old, new in zip(("exit", "stdout", "stderr"), before, after, strict=True)
            if old != new
        ]
        reports.append(
            {
                "id": key,
                "baseline_exit": before[0],
                "candidate_exit": after[0],
                "differences": differences,
            }
        )
    return {
        "schema_version": "1.0",
        "command": "shell-parity",
        "cases": reports,
        "matches": not any(case["differences"] for case in reports),
    }
