"""Detect tests that cannot fail (article 3): no assertion, always-true assertion, empty body,
swallowed failures. Python is parsed with `ast`; Java and Kotlin with a small tolerant scanner.

It judges what is written, not how strong the test is. Mutation testing measures strength.
"""

import ast
import re

from radea.static_review.files import Source
from radea.static_review.findings import Finding, quote

ASSERTISH = re.compile(
    r"(?i)^(?:assert\w*|verify\w*|check\w*|expect\w*|ensure\w*|validate\w*|compare\w*|should\w*"
    r"|must\w*|fail|raises|warns|approx|deprecated_call|raises_regex)$"
)
ALLOW = "radea: allow-no-assert"
# Assertion helpers are usually named waitAndAssertX / verify_y_called, so look inside identifiers.
ASSERT_INSIDE = re.compile(r"(?i)assert|verify|expect|ensure|validate|compare|should")
JAVA_TEST = re.compile(r"@(?:Test|ParameterizedTest|RepeatedTest)\b(?:\s*\((?P<args>[^)]*)\))?")
JAVA_SIGNATURE = re.compile(r"(?:\w+\s+)*?(?:void|fun)\s+(?P<name>`[^`]+`|\w+)\s*\(")
JAVA_ASSERT = re.compile(
    r"\b\w*(?:[Aa]ssert|[Vv]erify|[Ee]xpect|[Ee]nsure|[Vv]alidate|[Cc]ompare|[Ss]hould)\w*\b"
    r"|\b(?:fail|check\w*|require\w*|then\w*|isEqualTo|isTrue|isFalse)\b"
    r"|MatcherAssert|Truth\."
)
FIRST_CALL = re.compile(r"([A-Za-z_][\w.]*)\s*\(")
JAVA_TRIVIAL = re.compile(
    r"\bassert(?:True|That)\s*\(\s*true\s*\)|\bassertFalse\s*\(\s*false\s*\)"
    r"|\bassert(?:Equals|Same)\s*\(\s*(?P<a>[\w.\"]+)\s*,\s*(?P=a)\s*\)"
)
JAVA_SWALLOW = re.compile(
    r"catch\s*\(\s*(?:final\s+)?(?:\w+\s*:\s*)?(?:Exception|Throwable)(?:\s+\w+)?\s*\)\s*\{\s*\}"
)
SKIP_ANNOTATION = re.compile(r"@(?:Disabled|Ignore|Ignored)\b")


def review_tests(src: Source) -> list[Finding]:
    if src.path.endswith(".py") or src.path == "<stdin>":
        return _python(src)
    return _jvm(src)


# ---- Python -------------------------------------------------------------------------------
def _name(node: ast.AST) -> str:
    return node.attr if isinstance(node, ast.Attribute) else getattr(node, "id", "")


def _skipped(fn: ast.AST) -> bool:
    for decorator in getattr(fn, "decorator_list", []):
        text = ast.unparse(decorator)
        if re.search(r"\b(?:skip|skipif|xfail)\b", text):
            return True
    return False


def _tests(tree: ast.AST) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    found: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if item.name.startswith("test") and not _skipped(item):
                        found.append(item)
    for node in getattr(tree, "body", []):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("test") and not _skipped(node):
                found.append(node)
    return found


def _has_assertion(fn: ast.AST) -> bool:
    for node in ast.walk(fn):
        if isinstance(node, ast.Assert):
            return True
        if isinstance(node, ast.Call):
            called = _name(node.func)
            if ASSERTISH.match(called) or ASSERT_INSIDE.search(called):
                return True
        if isinstance(node, ast.Raise) and "AssertionError" in ast.dump(node):
            return True
    return False


def _trivial(node: ast.AST) -> bool:
    if isinstance(node, ast.Assert):
        test = node.test
        if isinstance(test, ast.Constant) and test.value:
            return True
        if (
            isinstance(test, ast.Compare)
            and len(test.ops) == 1
            and isinstance(test.ops[0], (ast.Eq, ast.Is))
            and ast.dump(test.left) == ast.dump(test.comparators[0])
        ):
            return True
    if isinstance(node, ast.Call):
        name, args = _name(node.func), node.args
        if name == "assertTrue" and args:
            return isinstance(args[0], ast.Constant) and bool(args[0].value)
        if name == "assertFalse" and args:
            return isinstance(args[0], ast.Constant) and not args[0].value
        if name in {"assertEqual", "assertIs"} and len(args) >= 2:
            return ast.dump(args[0]) == ast.dump(args[1])
    return False


def _empty(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for stmt in fn.body:
        if isinstance(stmt, ast.Pass):
            continue
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant):
            continue  # docstring or Ellipsis
        return False
    return True


def _swallows(fn: ast.AST) -> ast.ExceptHandler | None:
    for node in ast.walk(fn):
        if not isinstance(node, ast.Try):
            continue
        for handler in node.handlers:
            broad = handler.type is None or _name(handler.type) in {"Exception", "BaseException"}
            quiet = all(isinstance(s, (ast.Pass, ast.Continue)) for s in handler.body)
            if broad and quiet:
                return handler
    return None


def _python(src: Source) -> list[Finding]:
    try:
        tree = ast.parse(src.text)
    except (SyntaxError, ValueError, RecursionError):
        raise ValueError("not valid Python") from None
    findings: list[Finding] = []
    for fn in _tests(tree):
        first = min([fn.lineno, *(d.lineno for d in fn.decorator_list)])
        block = "\n".join(src.lines[first - 1 : fn.body[0].lineno])
        target = f"{fn.name}"

        def emit(rule: str, line: int, detail: str = "", _t: str = target) -> None:
            findings.append(Finding(rule, _t, src.path, line, quote(src.line(line)), detail))

        if _empty(fn):
            emit("TEST003", fn.lineno)
            continue
        if not _has_assertion(fn) and ALLOW not in block:
            call = next((n for n in ast.walk(fn) if isinstance(n, ast.Call)), None)
            emit("TEST001", fn.lineno, f"calls {_name(call.func)}()" if call else "")
        for node in ast.walk(fn):
            if _trivial(node):
                emit("TEST002", getattr(node, "lineno", fn.lineno))
        handler = _swallows(fn)
        if handler is not None:
            emit("TEST004", handler.lineno)
    return findings


# ---- Java / Kotlin ------------------------------------------------------------------------
def _strip(text: str) -> str:
    """Blank out comments and string contents but keep length and newlines."""
    out, i, n = [], 0, len(text)
    while i < n:
        two = text[i : i + 2]
        if two == "//":
            while i < n and text[i] != "\n":
                out.append(" ")
                i += 1
        elif two == "/*":
            while i < n and text[i : i + 2] != "*/":
                out.append("\n" if text[i] == "\n" else " ")
                i += 1
            out.append("  ")
            i += 2
        elif text[i] in "\"'":
            quote_char = text[i]
            out.append(quote_char)
            i += 1
            while i < n and text[i] != quote_char:
                if text[i] == "\\" and i + 1 < n:
                    out.append("  ")
                    i += 2
                    continue
                out.append("\n" if text[i] == "\n" else "x")
                i += 1
            out.append(quote_char)
            i += 1
        else:
            out.append(text[i])
            i += 1
    return "".join(out)


def _body(clean: str, start: int) -> tuple[int, int] | None:
    brace = clean.find("{", start)
    equals = clean.find("=", start)
    newline = clean.find("\n", start)
    if brace == -1 or (newline != -1 and equals != -1 and equals < brace and newline < brace):
        return (start, newline if newline != -1 else len(clean))
    depth = 0
    for i in range(brace, len(clean)):
        depth += clean[i] == "{"
        depth -= clean[i] == "}"
        if depth == 0:
            return (brace, i + 1)
    return None


def _jvm(src: Source) -> list[Finding]:
    findings: list[Finding] = []
    clean = _strip(src.text)
    for match in JAVA_TEST.finditer(clean):
        if "expected" in (match.group("args") or ""):
            continue
        before = clean[max(0, match.start() - 200) : match.start()]
        after = clean[match.end() : match.end() + 300]
        if SKIP_ANNOTATION.search(before) or SKIP_ANNOTATION.search(after.split("(")[0]):
            continue
        signature = JAVA_SIGNATURE.search(after)
        if not signature:
            continue
        paren = match.end() + signature.end()
        span = _body(clean, paren)
        if span is None:
            continue
        body = clean[span[0] : span[1]]
        original = src.text[match.start() : span[1]]
        line = src.text.count("\n", 0, match.end() + signature.start("name")) + 1
        target = signature["name"].strip("`")

        def emit(rule: str, detail: str = "", at: int = line, _t: str = target) -> None:
            findings.append(Finding(rule, _t, src.path, at, quote(src.line(at)), detail))

        inner = body.strip().strip("{}").strip()
        if not inner:
            emit("TEST003")
            continue
        if not JAVA_ASSERT.search(body) and ALLOW not in original:
            called = FIRST_CALL.search(inner)
            emit("TEST001", f"calls {called[1]}()" if called else "")
        if JAVA_TRIVIAL.search(body):
            emit("TEST002")
        if JAVA_SWALLOW.search(body):
            emit("TEST004")
    return findings
