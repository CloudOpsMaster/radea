"""Vulnerability report triage for Grype and Trivy JSON (articles 34, 37).

Deterministic by design: it groups, de-duplicates and ranks what a scanner already decided.
It never changes a severity, never drops a finding silently and never invents a fix version.
"""

import json
import re
from dataclasses import dataclass, field

from radea.static_review.files import Source
from radea.static_review.findings import Finding, quote

RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3, "negligible": 4, "unknown": 5}
GATED = {"critical", "high"}


@dataclass
class Vuln:
    id: str
    severity: str
    package: str
    version: str
    fixed: tuple[str, ...]
    target: str = ""
    purl: str = ""


@dataclass
class Group:
    package: str
    version: str
    vulns: list[Vuln] = field(default_factory=list)

    @property
    def worst(self) -> str:
        return min((v.severity for v in self.vulns), key=lambda s: RANK[s])

    @property
    def fixes(self) -> list[str]:
        return sorted({f for v in self.vulns for f in v.fixed})


def severity(value: object) -> str:
    text = str(value or "unknown").strip().lower()
    return text if text in RANK else "unknown"


def parse_report(src: Source) -> list[Vuln]:
    """Return vulnerabilities from a Grype or Trivy document; raise ValueError otherwise."""
    try:
        data = json.loads(src.text)
    except (ValueError, RecursionError):
        raise ValueError("not valid JSON") from None
    if isinstance(data, dict) and isinstance(data.get("matches"), list):
        return [v for v in (_grype(item) for item in data["matches"]) if v]
    if isinstance(data, dict) and isinstance(data.get("Results"), list):
        found: list[Vuln] = []
        for result in data["Results"]:
            if not isinstance(result, dict):
                raise ValueError("Invalid Trivy result object")
            items = result.get("Vulnerabilities") or []
            if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
                raise ValueError("Invalid Trivy vulnerability list")
            for item in items:
                found.append(_trivy(item, str(result.get("Target", ""))))
        return found
    raise ValueError("not a Grype or Trivy JSON report")


def _grype(item: object) -> Vuln | None:
    if not isinstance(item, dict):
        return None
    vuln, artifact = item.get("vulnerability") or {}, item.get("artifact") or {}
    if not isinstance(vuln, dict) or not isinstance(artifact, dict):
        raise ValueError("Invalid Grype vulnerability or artifact object")
    fix = vuln.get("fix") or {}
    versions = fix.get("versions") or [] if isinstance(fix, dict) else None
    if not isinstance(versions, list):
        raise ValueError("Invalid Grype fix versions")
    fixed = tuple(str(x) for x in versions if x)
    return Vuln(
        str(vuln.get("id", "?")),
        severity(vuln.get("severity")),
        str(artifact.get("name", "?")),
        str(artifact.get("version", "")),
        fixed,
        purl=str(artifact.get("purl") or ""),
    )


def _trivy(item: dict, target: str) -> Vuln:
    fixed = tuple(x.strip() for x in str(item.get("FixedVersion") or "").split(",") if x.strip())
    identifier = item.get("PkgIdentifier")
    purl = str(identifier.get("PURL") or "") if isinstance(identifier, dict) else ""
    return Vuln(
        str(item.get("VulnerabilityID", "?")),
        severity(item.get("Severity")),
        str(item.get("PkgName", "?")),
        str(item.get("InstalledVersion", "")),
        fixed,
        target,
        purl,
    )


def _version_key(value: str) -> tuple:
    return tuple(int(n) for n in re.findall(r"\d+", value)[:6])


def triage(src: Source, minimum: str) -> tuple[list[Finding], dict]:
    vulns = parse_report(src)
    unique = {(v.id, v.package, v.version): v for v in vulns}
    groups: dict[tuple[str, str], Group] = {}
    for vuln in unique.values():
        groups.setdefault(
            (vuln.package, vuln.version), Group(vuln.package, vuln.version)
        ).vulns.append(vuln)
    hidden = {name: 0 for name in RANK}
    findings: list[Finding] = []
    ranked = sorted(
        groups.values(),
        key=lambda g: (RANK[g.worst], not g.fixes, -len(g.vulns), g.package),
    )
    for group in ranked:
        shown = [v for v in group.vulns if RANK[v.severity] <= RANK[minimum]]
        for vuln in group.vulns:
            if RANK[vuln.severity] > RANK[minimum]:
                hidden[vuln.severity] += 1
        if not shown:
            continue
        worst = min((v.severity for v in shown), key=lambda s: RANK[s])
        fixable = any(v.fixed for v in shown if v.severity in GATED)
        rule = ("VULN001" if fixable else "VULN002") if worst in GATED else "VULN003"
        top = sorted(shown, key=lambda v: (RANK[v.severity], v.id))[:3]
        listed = ", ".join(f"{v.id} ({v.severity})" for v in top)
        more = f" +{len(shown) - len(top)} more" if len(shown) > len(top) else ""
        fixes = sorted({f for v in shown for f in v.fixed}, key=_version_key)
        upgrade = f"; fixed in {', '.join(fixes[:4])}" if fixes else "; no fix published"
        findings.append(
            Finding(
                rule,
                f"{group.package} {group.version}".strip(),
                src.path,
                None,
                quote(f"{listed}{more}{upgrade}"),
                f"{len(shown)} vulnerabilit{'y' if len(shown) == 1 else 'ies'}, worst {worst}",
                order=len(findings),
            )
        )
    counts = {name: 0 for name in RANK}
    for vuln in unique.values():
        counts[vuln.severity] += 1
    extra = {
        "vulnerabilities": len(unique),
        "by_scanner_severity": counts,
        "not_shown_below_minimum": {k: v for k, v in hidden.items() if v},
        "with_fix": sum(1 for v in unique.values() if v.fixed),
        "packages": len(groups),
        "minimum_severity": minimum,
    }
    return findings, extra
