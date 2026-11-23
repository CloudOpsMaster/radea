"""Write docs/rules.md from the rule catalog. `--check` exits 1 when the file is stale."""

import sys
from pathlib import Path

from radea.static_review.catalog import CATALOG

TITLES = {
    "K8S": "Kubernetes manifests (`k8s-review`)",
    "HELM": "Helm chart source (`k8s-review` on a chart directory)",
    "DF": "Dockerfile (`dockerfile-review`)",
    "CI": "CI configuration (`ci-review`)",
    "TF": "Terraform source (`tf-review`)",
    "VULN": "Vulnerability reports (`vuln-triage`)",
    "FLAKY": "Flaky tests (`flaky`)",
    "RS": "Right-sizing (`rightsize`)",
}


def render() -> str:
    lines = [
        "# Rule reference",
        "",
        "Generated from `src/radea/static_review/catalog.py` by `tools/gen_rules_doc.py`; do not",
        "edit by hand. The *Articles* column gives the numbers of the series articles each rule",
        "comes from. Severity is fixed per rule so a result never depends on a model.",
        "",
    ]
    for prefix, title in TITLES.items():
        rules = {k: v for k, v in CATALOG.items() if k.rstrip("0123456789") == prefix}
        if not rules:
            continue
        lines += [
            f"## {title}",
            "",
            "| Rule | Severity | Finding | Why it matters | Fix | Articles |",
        ]
        lines.append("| --- | --- | --- | --- | --- | --- |")
        for key, rule in rules.items():
            row = [
                key,
                rule.severity,
                rule.title,
                rule.why,
                rule.fix,
                ", ".join(map(str, rule.articles)),
            ]
            lines.append("| " + " | ".join(cell.replace("|", "\\|") for cell in row) + " |")
        lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    target = Path(__file__).resolve().parent.parent / "docs" / "rules.md"
    text = render()
    if "--check" in sys.argv:
        sys.exit(0 if target.exists() and target.read_text() == text else 1)
    target.write_text(text)
