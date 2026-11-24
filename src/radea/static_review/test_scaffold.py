"""Generate pytest cases from human-supplied inputs and expected outputs."""

import json
import keyword
from typing import Any

from radea.static_review.files import collect


def _identifier(value: str) -> bool:
    return value.isidentifier() and not keyword.iskeyword(value)


def render(path: str, module: str, function: str, limit: int) -> str:
    if not all(_identifier(part) for part in module.split(".")) or not _identifier(function):
        raise ValueError("Provide a dotted Python module and a function identifier")
    sources, _ = collect([path], max_bytes=limit)
    if len(sources) != 1:
        raise ValueError("Expected one test specification file")
    try:
        data = json.loads(sources[0].text)
    except (ValueError, RecursionError):
        raise ValueError("Invalid test specification JSON") from None
    cases = data.get("cases") if isinstance(data, dict) else None
    if not isinstance(cases, list) or not 1 <= len(cases) <= 100:
        raise ValueError("Expected 1–100 test cases")
    ids = set()
    checked: list[dict[str, Any]] = []
    for case in cases:
        if not isinstance(case, dict):
            raise ValueError("Expected test case objects")
        identity, args, kwargs = case.get("id"), case.get("args", []), case.get("kwargs", {})
        if not isinstance(identity, str) or not identity.strip() or len(identity) > 100:
            raise ValueError("Each test case requires a short ID")
        if identity in ids or not isinstance(args, list) or not isinstance(kwargs, dict):
            raise ValueError("Test IDs must be unique and arguments must be arrays or mappings")
        if not all(_identifier(name) for name in kwargs) or "expected" not in case:
            raise ValueError("Supply valid keyword arguments and an expected result for every case")
        ids.add(identity)
        checked.append(
            {"id": identity, "args": args, "kwargs": kwargs, "expected": case["expected"]}
        )
    try:
        encoded = json.dumps(checked, ensure_ascii=True, allow_nan=False)
    except (ValueError, RecursionError):
        raise ValueError("Test cases must use finite JSON data") from None
    return (
        '"""Generated from supplied expectations; review before committing."""\n\n'
        "import json\n\nimport pytest\n\n"
        f"from {module} import {function} as subject\n\n"
        f"CASES = json.loads({encoded!r})\n\n\n"
        '@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])\n'
        "def test_expected_result(case):\n"
        '    assert subject(*case["args"], **case["kwargs"]) == case["expected"]\n'
    )
