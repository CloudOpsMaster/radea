"""Classify a CI log and return ranked probable causes."""

from __future__ import annotations

import json
from pathlib import Path

from radea.core import llm
from radea.core import output as ui
from radea.core.config import Config
from radea.core.sanitizer import sanitize

_SYSTEM = """\
You are a senior DevOps engineer triaging a failing CI build.
Return JSON only — no markdown, no prose.

Schema:
{
  "category": "<code_error | dependency_drift | config_issue | flaky_infra | unknown>",
  "hypotheses": [
    {
      "title":       "<short cause name>",
      "confidence":  "<high | medium | low>",
      "description": "<one sentence>",
      "verify":      "<exact shell command or file path to confirm>"
    }
  ]
}

Rules:
- 2-3 hypotheses, most likely first.
- One sentence per description.
- verify must be a concrete shell command or file path.
- Never invent information not present in the log.
"""


def triage_log(
    *,
    log_path: str,
    sanitize_input: bool = True,
    output: str = "text",
    local: bool = False,
    dry_run: bool = False,
) -> dict | None:
    cfg = Config.from_env()
    if local:
        cfg.local = True

    raw = Path(log_path).read_text(errors="replace")
    san = sanitize(raw) if sanitize_input else None
    text = (san.text if san else raw)[: cfg.max_log_chars]
    redactions = san.redactions if san else 0

    if dry_run:
        ui.header("debug · dry-run", f"log: {log_path}")
        ui.console.print(f"\n[dim]Sanitizer:[/] [yellow]{redactions} redaction(s) applied[/]")
        ui.console.print(f"[dim]Payload size:[/] {len(text):,} chars")
        ui.console.print("\n[bold]Payload preview (first 20 lines):[/]")
        ui.console.print("\n".join(text.splitlines()[:20]), style="dim")
        return

    try:
        result = llm.call(system=_SYSTEM, user=f"CI LOG:\n{text}", cfg=cfg)
    except Exception as exc:  # noqa: BLE001
        result = {"category": "unknown", "hypotheses": [], "error": str(exc)}

    if output == "json":
        result["sanitizer"] = {"redactions": redactions}
        print(json.dumps(result, indent=2))
        return result

    ui.header("debug", f"log: {log_path}")
    ui.console.print(f"\n[bold]Failure type:[/] [cyan]{result.get('category', 'unknown')}[/]\n")
    ui.hypotheses_table(result.get("hypotheses", []))
    ui.sanitizer_line(redactions)
    if result.get("error"):
        ui.console.print(f"Error: {result['error']}", markup=False)
    ui.draft_warning()
    return result
