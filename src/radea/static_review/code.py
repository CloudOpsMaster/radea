"""High-confidence mechanical checks for Python source."""

import ast
from difflib import SequenceMatcher
from pathlib import Path

from radea.static_review.files import collect
from radea.static_review.findings import Finding, build_report


def review(paths: tuple[str, ...], limit: int, *, baseline: str | None = None) -> dict:
    old = None
    if baseline is not None:
        if len(paths) != 1 or paths[0] == baseline == "-" or Path(paths[0]).is_dir():
            raise ValueError("Baseline review requires one candidate file and at most one stdin")
        baseline_sources, _ = collect([baseline], max_bytes=limit)
        if len(baseline_sources) != 1:
            raise ValueError("Expected one Python baseline file")
        old = baseline_sources[0]
    sources, skipped = collect(paths, suffixes=(".py",), max_bytes=limit)
    if old is not None and len(sources) != 1:
        raise ValueError("Expected one Python candidate file")
    findings = []
    reviewed = []
    for source in sources:
        try:
            tree = ast.parse(source.text)
        except (SyntaxError, RecursionError):
            skipped.append({"path": source.path, "reason": "Invalid Python syntax"})
            continue
        reviewed.append(source.meta())
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for value in (*node.args.defaults, *node.args.kw_defaults):
                    if isinstance(value, (ast.List, ast.Dict, ast.Set)):
                        findings.append(Finding("CODE001", node.name, source.path, value.lineno))
            elif (
                isinstance(node, ast.ExceptHandler)
                and node.type is None
                and len(node.body) == 1
                and isinstance(node.body[0], ast.Pass)
            ):
                findings.append(Finding("CODE002", "exception handler", source.path, node.lineno))
            elif isinstance(node, ast.Compare) and any(
                isinstance(operator, (ast.Is, ast.IsNot))
                and any(
                    isinstance(value, ast.Constant)
                    and type(value.value) in (str, bytes, int, float, complex)
                    for value in (left, right)
                )
                for operator, left, right in zip(
                    node.ops, [node.left, *node.comparators[:-1]], node.comparators, strict=True
                )
            ):
                findings.append(Finding("CODE003", "comparison", source.path, node.lineno))
            elif isinstance(node, ast.Dict):
                seen: set[object] = set()
                for key in node.keys:
                    if not isinstance(key, ast.Constant):
                        continue
                    if key.value in seen:
                        findings.append(Finding("CODE004", "dictionary", source.path, key.lineno))
                    seen.add(key.value)
            elif isinstance(node, ast.Try):
                for statement in node.finalbody:
                    if isinstance(statement, ast.Return):
                        findings.append(Finding(
                            "CODE005", "finally block", source.path, statement.lineno
                        ))
    if old is not None:
        current = sources[0]
        if max(len(old.lines), len(current.lines)) > 5000:
            raise ValueError("Baseline review supports up to 5000 lines per file")
        matcher = SequenceMatcher(None, old.lines, current.lines)
        changed = {
            line
            for action, _, _, start, end in matcher.get_opcodes()
            if action != "equal"
            for line in range(start + 1, end + 1)
        }
        if skipped:
            raise ValueError("Cannot compare a candidate with invalid Python syntax")
        findings = [finding for finding in findings if finding.line in changed]
    report = build_report(
        "code-review",
        findings,
        reviewed,
        skipped=skipped,
        limitations="Local Python AST review. Human review covers behavior, business intent, "
        "cross-service consequences and architecture."
        + (" Baseline comparison reports findings on changed candidate lines." if old else ""),
    )
    if old is not None:
        report["baseline"] = old.meta()
    return report
