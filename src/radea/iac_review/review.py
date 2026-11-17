"""Explain IaC, flag IAM issues and destructive plan actions."""

from __future__ import annotations

import json
from pathlib import Path

from radea.core import llm
from radea.core import output as ui
from radea.core.config import Config
from radea.core.sanitizer import sanitize

_SYSTEM = """\
You are a senior DevOps engineer reviewing Terraform code and plan output.
Return JSON only — no markdown, no prose.

Schema:
{
  "summary": "<one paragraph: what this code provisions>",
  "destructive_actions": [{"resource": "<name>", "action": "<destroy|replace>"}],
  "findings": [
    {
      "severity":    "<high | medium | low | info>",
      "title":       "<short title>",
      "resource":    "<resource name or block>",
      "description": "<one sentence explaining the risk>"
    }
  ]
}

Rules:
- List every destroy or replace from the plan under destructive_actions.
- Flag Action * or Resource * in IAM as high severity.
- Flag missing encryption or public access as medium.
- One sentence per description.
- Never invent findings not supported by the input.
"""


def review_iac(
    *,
    tf_file: str | None,
    plan_file: str | None,
    context_file: str | None,
    output: str = "text",
    local: bool = False,
    dry_run: bool = False,
) -> dict | None:
    cfg = Config.from_env()
    if local:
        cfg.local = True

    parts: list[str] = []
    if tf_file:
        parts.append(f"TERRAFORM FILE:\n{sanitize(Path(tf_file).read_text(errors='replace')).text}")
    if plan_file:
        raw = sanitize(Path(plan_file).read_text(errors="replace")).text
        parts.append(f"PLAN JSON:\n{raw[: cfg.max_log_chars]}")
    if context_file:
        parts.append(
            f"TEAM CONVENTIONS:\n{sanitize(Path(context_file).read_text(errors='replace')).text}"
        )

    content = "\n\n".join(parts)[: cfg.max_log_chars]

    if dry_run:
        ui.header("iac-review · dry-run", tf_file or plan_file or "")
        ui.console.print(f"\n[dim]Payload size:[/] {len(content):,} chars")
        ui.console.print("\n[bold]Payload preview (first 20 lines):[/]")
        ui.console.print("\n".join(content.splitlines()[:20]), style="dim")
        return

    try:
        result = llm.call(system=_SYSTEM, user=content, cfg=cfg)
    except Exception as exc:  # noqa: BLE001
        result = {"summary": "", "destructive_actions": [], "findings": [], "error": str(exc)}

    if output == "json":
        print(json.dumps(result, indent=2))
        return result

    ui.header("iac-review", tf_file or plan_file or "")

    if result.get("destructive_actions"):
        ui.destructive_banner(result["destructive_actions"])

    if result.get("findings"):
        ui.console.print("\n[bold]Findings[/]")
        ui.findings_table(result["findings"])

    if result.get("summary"):
        ui.console.print(f"\n[bold]What this code provisions[/]\n  {result['summary']}\n")

    if result.get("error"):
        ui.console.print(f"Error: {result['error']}", markup=False)
    ui.draft_warning()
    return result
