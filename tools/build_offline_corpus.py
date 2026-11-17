"""Reproduce local Python failures. No production data, network or credentials."""

import json
import subprocess
import sys
import sysconfig
from pathlib import Path

# Family-level splits: message variants of a family never cross partitions.
FAMILIES = {
    "code_error": ["1 / 0", "None.missing_attribute", "int(1) + 'text'", "[][3]"],
    "dependency_drift": [
        "import radea_nonexistent_dependency",
        "from math import nonexistent_symbol",
        "__import__('radea_missing_package')",
        "from json import radea_missing_export",
    ],
    "config_issue": [
        "open('radea-nonexistent-input.txt')",
        "open('.', 'rb')",
        "import os; os.chdir('radea-missing-directory')",
        "open('/dev/null/child')",
    ],
    "flaky_infra": [
        "import subprocess; subprocess.run(['sleep', '1'], timeout=0.001)",
        "from concurrent.futures import Future; Future().result(timeout=0.001)",
        "import asyncio; asyncio.run(asyncio.wait_for(asyncio.sleep(1), timeout=0.001))",
        "import threading; threading.Barrier(2).wait(timeout=0.001)",
    ],
    "unknown": [
        "int('not-a-number')",
        "assert False, 'invariant failed'",
        "bytes([255]).decode('utf-8')",
        "next(iter([]))",
    ],
}


def main():
    rows = []
    for label, families in FAMILIES.items():
        for family, operation in enumerate(families):
            split = ("train", "train", "calibration", "test")[family]
            code = operation + "\n"
            proc = subprocess.run(
                [sys.executable, "-I", "-c", code],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            if proc.returncode == 0:
                raise RuntimeError("Expected failure did not occur")
            rows.append(
                {
                    "id": f"{label}-{family}",
                    "family": f"{label}-{family}",
                    "split": split,
                    "category": label,
                    "text": proc.stderr.strip().replace(
                        str(Path(sysconfig.get_path("stdlib")).resolve()), "<python-stdlib>"
                    ),
                    "origin": "reproduced_python_process",
                    "reproducer": code,
                }
            )
    Path("examples/offline/corpus.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "provenance": "Locally reproduced Python failures; not production incidents",
                "python": sys.version.split()[0],
                "cases": rows,
            },
            indent=2,
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
