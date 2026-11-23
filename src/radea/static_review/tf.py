"""Terraform source review (articles 11, 16, 32, 33, 38). Tolerant HCL reader, no dependencies.

This is a reader for the shapes the rules need, not a full HCL parser: it understands blocks,
attributes, strings, comments, heredocs and bracketed expressions, and skips what it does not.
"""

import re
from dataclasses import dataclass, field

from radea.static_review.files import Source
from radea.static_review.findings import Finding, quote

SECRET_NAME = re.compile(r"(?i)password|passwd|secret|token|api[_-]?key|private[_-]?key|credential")
NOT_A_SECRET = re.compile(
    r"(?i)(?:_name|_arn|_id|_length|_version|_rotation_days|_enabled|_file|_path|_url|_ref"
    r"|_type|_policy|_kms_key|_secret_id)$"
)
REFERENCE = re.compile(r"^(?:var|local|data|module|aws_|random_|each|self|azurerm_|google_)\b")
# Values that mean "the whole internet" in rules; nothing here binds a socket.
WORLD = {"0.0.0.0/0", "::/0", "*", "internet", "any", "0.0.0.0"}  # nosec B104
SENSITIVE_PORTS = {21, 22, 23, 1433, 3306, 3389, 5432, 5984, 6379, 9200, 11211, 27017}
CIDR_KEYS = (
    "cidr_blocks", "ipv6_cidr_blocks", "cidr_ipv4", "cidr_ipv6", "source_ranges",
    "source_address_prefix", "source_address_prefixes",
)  # fmt: skip
ENCRYPTION_KEYS = {"storage_encrypted", "encrypted", "encryption_enabled", "enable_encryption"}
PUBLIC_TRUE = {"publicly_accessible", "public_network_access_enabled"}
BLOCK_PUBLIC_FALSE = {
    "block_public_acls", "block_public_policy", "ignore_public_acls", "restrict_public_buckets",
}  # fmt: skip
STATEFUL = {
    "aws_db_instance", "aws_rds_cluster", "aws_s3_bucket", "aws_dynamodb_table", "aws_ebs_volume",
    "aws_efs_file_system", "aws_kms_key", "google_sql_database_instance", "google_storage_bucket",
    "azurerm_mssql_database", "azurerm_postgresql_flexible_server", "azurerm_storage_account",
}  # fmt: skip


@dataclass
class Block:
    kind: str
    labels: list[str]
    line: int
    attrs: dict[str, tuple[str, int]] = field(default_factory=dict)
    children: list["Block"] = field(default_factory=list)

    def literal(self, name: str) -> str | None:
        item = self.attrs.get(name)
        if item is None:
            return None
        match = re.fullmatch(r'\s*"([^"]*)"\s*', item[0])
        return match[1] if match and "${" not in match[1] else None

    def boolean(self, name: str) -> bool | None:
        item = self.attrs.get(name)
        value = item[0].strip().lower() if item else ""
        return {"true": True, "false": False}.get(value)

    def strings(self, name: str) -> list[str]:
        item = self.attrs.get(name)
        return re.findall(r'"([^"]*)"', item[0]) if item else []


class Reader:
    def __init__(self, text: str) -> None:
        self.t, self.i, self.n = text, 0, len(text)
        self.line = 1

    def peek(self, k: int = 0) -> str:
        return self.t[self.i + k] if self.i + k < self.n else ""

    def advance(self) -> str:
        ch = self.t[self.i]
        self.i += 1
        if ch == "\n":
            self.line += 1
        return ch

    def skip_space(self, newlines: bool = True) -> None:
        while self.i < self.n:
            ch = self.peek()
            if ch in " \t\r" or (newlines and ch == "\n"):
                self.advance()
            elif ch == "#" or (ch == "/" and self.peek(1) == "/"):
                while self.i < self.n and self.peek() != "\n":
                    self.advance()
            elif ch == "/" and self.peek(1) == "*":
                self.advance(), self.advance()
                while self.i < self.n and not (self.peek() == "*" and self.peek(1) == "/"):
                    self.advance()
                for _ in range(2):
                    if self.i < self.n:
                        self.advance()
            else:
                return

    def string(self) -> str:
        out = [self.advance()]
        depth = 0
        while self.i < self.n:
            ch = self.advance()
            out.append(ch)
            if ch == "\\" and self.i < self.n:
                out.append(self.advance())
            elif ch == "$" and self.peek() == "{":
                out.append(self.advance())
                depth += 1
            elif depth and ch == "{":
                depth += 1
            elif depth and ch == "}":
                depth -= 1
            elif ch == '"' and not depth:
                break
        return "".join(out)

    def heredoc(self) -> str:
        match = re.match(r"<<-?\s*([A-Za-z_][A-Za-z0-9_]*)", self.t[self.i : self.i + 80])
        if not match:
            return self.advance()
        tag, out = match[1], []
        while self.i < self.n and self.peek() != "\n":
            out.append(self.advance())
        while self.i < self.n:
            start = self.i
            while self.i < self.n and self.peek() != "\n":
                self.advance()
            row = self.t[start : self.i]
            out.append("\n" + row)
            if row.strip() == tag:
                break
            if self.i < self.n:
                self.advance()
        return "".join(out)

    def expression(self) -> str:
        out, depth = [], 0
        while self.i < self.n:
            ch = self.peek()
            if (ch == "\n" or ch == "}") and depth <= 0:
                break  # a bare } closes a one-line block such as `lifecycle { x = true }`
            if ch == '"':
                out.append(self.string())
            elif ch == "<" and self.peek(1) == "<":
                out.append(self.heredoc())
            elif ch == "#" or (ch == "/" and self.peek(1) in "/*"):
                self.skip_space(newlines=False)
            else:
                depth += ch in "([{"
                depth -= ch in ")]}"
                out.append(self.advance())
        return "".join(out).strip()

    def body(self, nested: bool) -> tuple[dict, list[Block]]:
        attrs: dict[str, tuple[str, int]] = {}
        blocks: list[Block] = []
        while True:
            self.skip_space()
            if self.i >= self.n:
                return attrs, blocks
            if self.peek() == "}":
                if nested:
                    self.advance()
                    return attrs, blocks
                self.advance()
                continue
            line = self.line
            match = re.match(r"[A-Za-z_][A-Za-z0-9_-]*", self.t[self.i : self.i + 200])
            if not match:
                self.advance()
                continue
            name = match[0]
            self.i += len(name)
            self.skip_space(newlines=False)
            if self.peek() == "=" and self.peek(1) != "=":
                self.advance()
                self.skip_space(newlines=False)
                attrs[name] = (self.expression(), line)
                continue
            labels: list[str] = []
            while self.i < self.n and self.peek() not in "{\n":
                if self.peek() == '"':
                    labels.append(self.string().strip('"'))
                else:
                    label = re.match(r"[A-Za-z0-9_.-]+", self.t[self.i : self.i + 200])
                    if not label:
                        self.advance()
                    else:
                        labels.append(label[0])
                        self.i += len(label[0])
                self.skip_space(newlines=False)
            if self.peek() == "{":
                self.advance()
                inner, children = self.body(True)
                blocks.append(Block(name, labels, line, inner, children))
            else:
                self.expression()


def parse(text: str) -> list[Block]:
    return Reader(text).body(False)[1]


def _int(block: Block, name: str) -> int | None:
    item = block.attrs.get(name)
    return int(item[0].strip()) if item and item[0].strip().isdigit() else None


def _ports(block: Block) -> tuple[bool, set[int]]:
    """(all ports, sensitive or explicit ports) for a rule or ingress block."""
    if block.literal("protocol") in {"-1", "all", "All", "*"}:
        return True, set()
    everything = False
    ports: set[int] = set()
    low, high = _int(block, "from_port"), _int(block, "to_port")
    if low is not None and high is not None:
        if low == 0 and high in {0, 65535}:
            everything = True
        else:
            ports.update(p for p in SENSITIVE_PORTS if low <= p <= high)
            ports.update({low, high})
    elif (single := low if low is not None else high) is not None:
        ports.add(single)
    specs = [
        *block.strings("ports"), *block.strings("destination_port_range"),
        *block.strings("destination_port_ranges"), *block.strings("port_range"),
    ]  # fmt: skip
    for spec in specs:
        if spec in {"*", "0-65535"}:
            everything = True
        elif spec.isdigit():
            ports.add(int(spec))
        elif m := re.fullmatch(r"(\d+)-(\d+)", spec):
            ports.update(p for p in SENSITIVE_PORTS if int(m[1]) <= p <= int(m[2]))
    return everything, ports


def _world_open(block: Block) -> bool:
    values = [v.lower() for key in CIDR_KEYS for v in block.strings(key)]
    return any(v in WORLD for v in values)


def review_terraform(src: Source) -> list[Finding]:
    findings: list[Finding] = []
    blocks = parse(src.text)

    def emit(rule: str, target: str, line: int, detail: str = "", evidence: str | None = None):
        text = quote(src.line(line)) if evidence is None else evidence
        findings.append(Finding(rule, target, src.path, line, text, detail))

    for block in blocks:
        if block.kind == "terraform":
            _versions(block, emit)
        elif block.kind == "module":
            _module(block, emit)
        elif block.kind == "variable":
            _variable(block, emit)
        elif block.kind == "resource" and len(block.labels) >= 2:
            _resource(block, emit)
    return findings


def _versions(block: Block, emit) -> None:
    for child in block.children:
        if child.kind != "required_providers":
            continue
        for name, (expr, line) in child.attrs.items():
            version = re.search(r'version\s*=\s*"([^"]*)"', expr)
            text = version[1] if version else (expr.strip('"') if expr.startswith('"') else "")
            if not text or _open_ended(text):
                detail = f"{name}: {text or 'no version'}"
                emit("TF006", f"provider {name}", line, detail)


def _open_ended(constraint: str) -> bool:
    parts = [p.strip() for p in constraint.split(",")]
    has_upper = any(p.startswith(("<", "~>", "=")) or re.match(r"^\d", p) for p in parts)
    return not has_upper and any(p.startswith((">", "!=")) for p in parts)


def _module(block: Block, emit) -> None:
    source = block.literal("source") or ""
    if not source or source.startswith(("./", "../")):
        return
    target = f"module.{block.labels[0] if block.labels else '?'}"
    if "git::" in source or source.startswith(("github.com", "git@", "https://", "ssh://")):
        ref = re.search(r"\?ref=([^&]+)", source)
        if not ref or ref[1].lower() in {"main", "master", "develop", "head"}:
            emit(
                "TF006",
                target,
                block.attrs["source"][1],
                f"source ref: {ref[1] if ref else 'none'}",
            )
    elif "version" not in block.attrs:
        emit("TF006", target, block.line, "registry module without version")
    elif _open_ended(block.literal("version") or ""):
        emit("TF006", target, block.attrs["version"][1], f"version {block.literal('version')}")


def _variable(block: Block, emit) -> None:
    name = block.labels[0] if block.labels else ""
    default = block.literal("default")
    if default and SECRET_NAME.search(name) and not NOT_A_SECRET.search(name):
        emit("TF003", f"variable.{name}", block.attrs["default"][1],
             evidence=f"default for {name}: literal value not shown")  # fmt: skip


def _resource(block: Block, emit) -> None:
    kind, name = block.labels[0], block.labels[1]
    target = f"{kind}.{name}"
    nodes = [block, *block.children]
    for node in nodes:
        for attr, (expr, line) in node.attrs.items():
            value = node.literal(attr)
            if (
                value
                and SECRET_NAME.search(attr)
                and not NOT_A_SECRET.search(attr)
                and not REFERENCE.match(value)
                and "sensitive" not in attr.lower()
            ):
                emit("TF003", target, line, attr, evidence=f"{attr}: literal value not shown")
            if attr in ENCRYPTION_KEYS and node.boolean(attr) is False:
                emit("TF004", target, line, attr)
            if attr in PUBLIC_TRUE and node.boolean(attr) is True:
                emit("TF005", target, line, attr)
            if attr in BLOCK_PUBLIC_FALSE and node.boolean(attr) is False:
                emit("TF005", target, line, attr)
            if attr == "acl" and (value or "").startswith("public-read"):
                emit("TF005", target, line, f"acl {value}")
            if (
                (attr == "skip_final_snapshot" and node.boolean(attr) is True)
                or (attr == "force_destroy" and node.boolean(attr) is True)
                or (attr == "deletion_protection" and node.boolean(attr) is False)
            ):
                emit("TF007", target, line, attr)
    _network(block, target, emit)
    if kind in STATEFUL:
        guard = next((c for c in block.children if c.kind == "lifecycle"), None)
        if guard is None or guard.boolean("prevent_destroy") is not True:
            emit("TF008", target, block.line)


def _network(block: Block, target: str, emit) -> None:
    kind = block.labels[0]
    candidates: list[Block] = []
    if kind == "aws_security_group_rule" and block.literal("type") == "ingress":
        candidates.append(block)
    elif kind == "aws_security_group":
        candidates.extend(c for c in block.children if c.kind == "ingress")
    elif kind == "aws_vpc_security_group_ingress_rule":
        candidates.append(block)
    elif kind == "google_compute_firewall" and block.literal("direction") != "EGRESS":
        candidates.append(block)
    elif kind == "azurerm_network_security_rule":
        if block.literal("direction") == "Inbound" and block.literal("access") == "Allow":
            candidates.append(block)
    elif kind == "aws_network_acl_rule" and block.boolean("egress") is not True:
        if block.literal("rule_action") == "allow":
            candidates.append(block)
    for candidate in candidates:
        if kind == "google_compute_firewall":
            ports = Block("allow", [], candidate.line)
            for child in candidate.children:
                ports.attrs.update(child.attrs)
            everything, listed = _ports(ports)
            if not child_has_ports(candidate):
                everything = True
        else:
            everything, listed = _ports(candidate)
        if not _world_open(candidate):
            continue
        for key in CIDR_KEYS:
            if key in candidate.attrs:
                line = candidate.attrs[key][1]
                break
        else:
            line = candidate.line
        rule = "TF001" if everything or (listed & SENSITIVE_PORTS) else "TF002"
        emit(rule, target, line, "all ports" if everything else ",".join(map(str, sorted(listed))))


def child_has_ports(block: Block) -> bool:
    return any("ports" in c.attrs for c in block.children)
