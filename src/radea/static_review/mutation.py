"""Run one trusted Python test file against isolated, single-change module variants."""

import ast
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from radea.core.sanitizer import clean
from radea.static_review.files import Source, collect

COMPARISONS: dict[type[ast.cmpop], type[ast.cmpop]] = {
    ast.Lt: ast.LtE,
    ast.LtE: ast.Lt,
    ast.Gt: ast.GtE,
    ast.GtE: ast.Gt,
    ast.Eq: ast.NotEq,
    ast.NotEq: ast.Eq,
}


def _source(path: str, limit: int) -> Source:
    files, _ = collect([path], max_bytes=limit)
    if len(files) != 1 or Path(files[0].path).suffix != ".py":
        raise ValueError("Mutation testing requires two regular Python files")
    return files[0]


def _targets(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            for index, operation in enumerate(node.ops):
                if type(operation) in COMPARISONS:
                    yield node, index, type(operation).__name__
        elif isinstance(node, ast.Constant) and isinstance(node.value, bool):
            yield node, None, "boolean"


def _run_files(files: dict[str, str], test_path: str, timeout: int, import_root: str = ".") -> str:
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in {"PYTHONPATH", "PYTEST_ADDOPTS", "PYTEST_PLUGINS"}
    }
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    with tempfile.TemporaryDirectory(prefix="radea-mutation-") as directory:
        work = Path(directory)
        env["PYTHONPATH"] = str(work / import_root)
        for name, content in files.items():
            target = work / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pytest", "-q", "--", test_path],
                cwd=work,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return "timeout"
    return {0: "passed", 1: "failed"}.get(result.returncode, "error")


def _variants(tree: ast.AST, targets):
    for node, index, operation in targets:
        if isinstance(node, ast.Compare):
            original = node.ops[index]
            node.ops[index] = COMPARISONS[type(original)]()
        else:
            original = node.value
            node.value = not original
        try:
            variant = ast.unparse(tree)
        except RecursionError:
            raise ValueError("Python module is too complex to render mutations") from None
        finally:
            if isinstance(node, ast.Compare):
                node.ops[index] = original
            else:
                node.value = original
        yield node.lineno, operation, variant


def _statistics(mutants: list[dict]) -> dict:
    killed = sum(item["outcome"] == "killed" for item in mutants)
    survived = sum(item["outcome"] == "survived" for item in mutants)
    return {
        "tested_mutants": len(mutants),
        "killed": killed,
        "survived": survived,
        "inconclusive": len(mutants) - killed - survived,
        "mutants": mutants,
    }


def test(module_path: str, tests_path: str, limit: int, maximum: int, timeout: int) -> dict:
    module = _source(module_path, limit)
    tests = _source(tests_path, limit)
    module_name, test_name = Path(module.path).name, Path(tests.path).name
    if module_name == test_name or not Path(module_name).stem.isidentifier():
        raise ValueError("Module must have an importable name distinct from the test file")
    try:
        tree = ast.parse(module.text)
        targets = list(_targets(tree))
    except (SyntaxError, RecursionError):
        raise ValueError("Unable to parse Python module for mutation testing") from None
    if not targets:
        raise ValueError("No supported mutations found")
    files = {module_name: module.text, test_name: tests.text}
    if _run_files(files, test_name, timeout) != "passed":
        raise ValueError("Baseline pytest run did not pass in the temporary workspace")

    mutants = []
    for line, operation, variant in _variants(tree, targets[:maximum]):
        outcome = _run_files({**files, module_name: variant}, test_name, timeout)
        mutants.append(
            {
                "line": line,
                "operation": operation,
                "outcome": {"passed": "survived", "failed": "killed"}.get(outcome, outcome),
            }
        )
    return clean(
        {
            "schema_version": "1.0",
            "command": "mutation-test",
            "sources": {"module": module.meta(), "tests": tests.meta()},
            "available_mutants": len(targets),
            **_statistics(mutants),
        }
    )


def suite(root: str, package: str, tests: str, limit: int, maximum: int, timeout: int) -> dict:
    base = Path(root).resolve()
    package_path, tests_path = ((base / name).resolve() for name in (package, tests))
    if not all(
        path.is_relative_to(base) and path != base and path.is_dir()
        for path in (package_path, tests_path)
    ):
        raise ValueError("Choose package and test directories inside the project root")
    if package_path.is_relative_to(tests_path) or tests_path.is_relative_to(package_path):
        raise ValueError("Package and test directories must be separate")
    package_sources, package_skipped = collect(
        [str(package_path)], suffixes=(".py",), max_bytes=limit, max_total_bytes=limit
    )
    test_sources, test_skipped = collect(
        [str(tests_path)], suffixes=(".py",), max_bytes=limit, max_total_bytes=limit
    )
    if package_skipped or test_skipped or not package_sources or not test_sources:
        raise ValueError("Expected readable Python sources and tests within the input bounds")
    if sum(len(source.text.encode()) for source in package_sources + test_sources) > limit:
        raise ValueError("Package mutation inputs exceed RADEA_MAX_INPUT_BYTES")
    files = {
        Path(source.path).relative_to(base).as_posix(): source.text
        for source in package_sources + test_sources
    }
    candidates = []
    available = 0
    for source in sorted(package_sources, key=lambda item: item.path):
        try:
            tree = ast.parse(source.text)
            targets = list(_targets(tree))
        except (SyntaxError, RecursionError):
            raise ValueError("Unable to parse a package module for mutation testing") from None
        if available < maximum and targets:
            name = Path(source.path).relative_to(base).as_posix()
            candidates.append((name, tree, targets[: maximum - available]))
        available += len(targets)
    if not available:
        raise ValueError("No supported mutations found")
    tests_name = tests_path.relative_to(base).as_posix()
    import_root = package_path.parent.relative_to(base).as_posix()
    if _run_files(files, tests_name, timeout, import_root) != "passed":
        raise ValueError("Baseline pytest suite did not pass in the temporary workspace")
    mutants = []
    for name, tree, targets in candidates:
        for line, operation, variant in _variants(tree, targets):
            outcome = _run_files({**files, name: variant}, tests_name, timeout, import_root)
            mutants.append(
                {
                    "module": name,
                    "line": line,
                    "operation": operation,
                    "outcome": {"passed": "survived", "failed": "killed"}.get(outcome, outcome),
                }
            )
    return clean(
        {
            "schema_version": "1.0",
            "command": "mutation-suite",
            "modules": len(package_sources),
            "test_files": len(test_sources),
            "available_mutants": available,
            **_statistics(mutants),
        }
    )
