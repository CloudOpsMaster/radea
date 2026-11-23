"""Documentation must not drift from the code it describes."""

import subprocess
import sys
from pathlib import Path

from radea.cli import main
from radea.static_review.catalog import CATALOG

ROOT = Path(__file__).resolve().parent.parent
README = (ROOT / "README.md").read_text()


def test_rules_reference_is_up_to_date():
    done = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "gen_rules_doc.py"), "--check"], check=False
    )
    assert done.returncode == 0, "run: python tools/gen_rules_doc.py"


def test_every_rule_is_documented_and_traces_to_an_article():
    text = (ROOT / "docs" / "rules.md").read_text()
    for key, rule in CATALOG.items():
        assert f"| {key} |" in text, key
        assert rule.articles, f"{key} has no source article"
        assert rule.why.strip() and rule.fix.strip(), key


def test_readme_mentions_every_command():
    missing = [name for name in main.commands if f"radea {name}" not in README]
    assert not missing, missing


def test_static_review_guide_mentions_every_review_command():
    guide = (ROOT / "docs" / "static-review.md").read_text()
    for name in ("k8s-review", "dockerfile-review", "ci-review", "tf-review", "vuln-triage",
                 "flaky", "rightsize", "changelog", "policy-check", "rules"):  # fmt: skip
        assert f"`{name}" in guide, name


def test_feature_matrix_covers_eighty_articles_and_only_cites_real_rules():
    import re

    text = (ROOT / "docs" / "feature-matrix.uk.md").read_text()
    numbers = [int(m) for m in re.findall(r"^\| (\d+) \|", text, re.MULTILINE)]
    assert numbers == list(range(1, 81))
    for rule in set(re.findall(r"\b(?:K8S|HELM|DF|CI|TF|VULN|FLAKY|RS)\d{3}\b", text)):
        assert rule in CATALOG, rule
