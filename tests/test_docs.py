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
    names = (
        "k8s-review", "dockerfile-review", "ci-review", "tf-review", "test-review", "vuln-triage",
        "flaky", "rightsize", "changelog", "policy-check", "rules",
    )  # fmt: skip
    for name in names:
        assert f"`{name}" in guide, name


def test_feature_matrix_covers_eighty_articles_and_only_cites_real_rules():
    import re
    from collections import Counter

    text = (ROOT / "docs" / "feature-matrix.md").read_text()
    rows = [
        line.strip("|").split(" | ") for line in text.splitlines() if re.match(r"^\| \d+ \|", line)
    ]
    assert all(len(row) == 6 and all(cell.strip() for cell in row) for row in rows)
    assert [int(row[0]) for row in rows] == list(range(1, 81))
    labels = {"Covered", "Partial", "Aligned", "Out of scope"}
    counts = Counter(row[4] for row in rows)
    assert counts.keys() <= labels
    totals = ", ".join(
        f"{label.lower()} — {counts[label]}"
        for label in (
            "Covered",
            "Partial",
            "Aligned",
            "Out of scope",
        )
    )
    assert f"Summary: {totals}." in text
    for rule in set(re.findall(r"\b(?:K8S|HELM|DF|CI|TF|VULN|FLAKY|RS|TH|CODE)\d{3}\b", text)):
        assert rule in CATALOG, rule
    corpus = ROOT / "articles"
    if corpus.is_dir():
        files = [*corpus.glob("[0-9][0-9]-*.md"), *(corpus / "radea").glob("[0-9][0-9]-*.md")]
        if files:
            sources = sorted((int(path.name[:2]), path) for path in files)
            assert [number for number, _ in sources] == list(range(1, 81))
            for number, path in sources:
                title = path.read_text(encoding="utf-8").splitlines()[0].removeprefix("# ")
                assert title == rows[number - 1][1], number


def test_documented_counts_match_the_code():
    from radea.core import offline

    changelog = (ROOT / "CHANGELOG.md").read_text()
    offline_doc = (ROOT / "docs" / "offline.md").read_text()
    assert f"{len(CATALOG)} rules" in changelog
    assert f"{len(offline.RULES)} in total" in changelog
    assert f"recognises {len(offline.RULES)} failure" in offline_doc
    assert f"from 8 to {len(offline.RULES)} signatures" in offline_doc
