"""Cluster incident logs and draft a postmortem timeline."""

from __future__ import annotations

import json
from pathlib import Path

from radea.core import llm
from radea.core import output as ui
from radea.core.config import Config
from radea.core.sanitizer import sanitize

_SYSTEM = """\
You are a senior SRE triaging an incident.
Return JSON only — no markdown, no prose.

Schema:
{
  "patterns": [
    {
      "label":        "<short pattern name>",
      "count":        <int>,
      "severity":     "<high | medium | low>",
      "example_line": "<one representative log line>",
      "description":  "<one sentence>"
    }
  ],
  "timeline": [
    {"time": "<HH:MM or relative>", "event": "<one sentence>", "source_line": "<log line>"}
  ],
  "probable_cause":    "<one sentence>",
  "postmortem_draft":  "<2-3 sentences: what happened, impact, probable root cause>"
}

Rules:
- Collapse similar lines into 3-7 patterns regardless of log size.
- Timeline: 3-8 key events in chronological order.
- Link every timeline event to a specific source_line.
- Never invent events not present in the input.
"""


def compress_logs(
    *,
    logs_path: str,
    metrics_path: str | None,
    baseline: str = "7d",
    output: str = "text",
    local: bool = False,
    dry_run: bool = False,
) -> dict | None:
    cfg = Config.from_env()
    if local:
        cfg.local = True

    san = sanitize(_read_logs(logs_path))
    content = san.text[: cfg.max_log_chars]

    if metrics_path:
        metrics = sanitize(Path(metrics_path).read_text(errors="replace"))
        content += f"\n\nMETRICS (baseline: {baseline}):\n{metrics.text[:4_000]}"

    if dry_run:
        ui.header("triage · dry-run", f"logs: {logs_path}")
        ui.console.print(f"\n[dim]Sanitizer:[/] [yellow]{san.redactions} redaction(s) applied[/]")
        ui.console.print(f"[dim]Payload size:[/] {len(content):,} chars")
        ui.console.print("\n[bold]Payload preview (first 20 lines):[/]")
        ui.console.print("\n".join(content.splitlines()[:20]), style="dim")
        return

    try:
        result = llm.call(system=_SYSTEM, user=content, cfg=cfg)
    except Exception as exc:  # noqa: BLE001
        result = {"patterns": [], "timeline": [], "probable_cause": "", "error": str(exc)}

    if output == "json":
        result["sanitizer"] = {"redactions": san.redactions}
        print(json.dumps(result, indent=2))
        return result

    ui.header("triage", f"logs: {logs_path}")

    if result.get("patterns"):
        ui.console.print("\n[bold]Log patterns[/]")
        ui.patterns_table(result["patterns"])

    if result.get("timeline"):
        ui.console.print("\n[bold]Timeline[/]")
        ui.timeline_table(result["timeline"])

    if result.get("probable_cause"):
        ui.console.print(f"\n[bold]Probable cause:[/] {result['probable_cause']}\n")

    if result.get("postmortem_draft"):
        ui.console.print("[bold]Postmortem draft[/]")
        ui.console.print(f"  {result['postmortem_draft']}\n")

    ui.sanitizer_line(san.redactions)
    if result.get("error"):
        ui.console.print(f"Error: {result['error']}", markup=False)
    ui.draft_warning()
    return result


def _read_logs(path: str) -> str:
    p = Path(path)
    if p.is_dir():
        return "\n".join(f.read_text(errors="replace") for f in sorted(p.glob("*.log")))
    return p.read_text(errors="replace")
