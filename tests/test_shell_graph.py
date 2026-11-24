import json
import shutil

import pytest
from click.testing import CliRunner

from radea.cli import main


@pytest.mark.skipif(shutil.which("shfmt") is None, reason="optional shfmt parser unavailable")
def test_shell_graph_traces_literal_calls_without_exec_or_escaping_root(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    outside = tmp_path / "outside.sh"
    outside.write_text("source ./unexpected.sh\n")
    (root / "escape.sh").symlink_to(outside)
    entry = root / "main.sh"
    entry.write_text(
        "# source ./comment.sh\n"
        "cat <<'TEXT'\n. ./not-a-call.sh\nTEXT\n"
        'if true; then source "./part one.sh"; fi\n'
        '. "$UNKNOWN"\n'
        ". ./escape.sh\n"
        f'touch "{root / "SHOULD_NOT_EXIST"}"\n'
    )
    (root / "part one.sh").write_text("bash ./leaf.sh\n")
    (root / "leaf.sh").write_text("source ./main.sh\n")
    result = CliRunner().invoke(main, [
        "shell-graph", str(entry), "--root", str(root), "--fail-on-partial",
    ])
    assert result.exit_code == 2, result.output
    report = json.loads(result.output)
    assert [source["path"] for source in report["sources"]] == [
        "main.sh", "part one.sh", "leaf.sh",
    ]
    assert [(ref["line"], ref["target"], ref["unresolved"]) for ref in report["references"]] == [
        (5, "part one.sh", None), (6, None, "dynamic_or_unsupported"),
        (7, None, "outside_root"), (1, "leaf.sh", None), (1, "main.sh", None),
    ]
    assert not (root / "SHOULD_NOT_EXIST").exists()
