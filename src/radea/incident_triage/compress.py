"""Evidence-based advisory analysis with shared runtime guardrails."""

from pathlib import Path

from radea.core.runtime import run_command

_SYSTEM = """You are a senior SRE triaging an incident.
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

Root cause is only an unverified hypothesis. Use blameless system-focused language.
Humans own final conclusions and action items.
"""


def compress_logs(
    *,
    logs_path: str,
    metrics_path: str | None,
    baseline: str = "7d",
    output: str = "text",
    local: bool = False,
    dry_run: bool = False,
) -> dict:
    source = Path(logs_path)
    paths = [str(p) for p in sorted(source.glob("*.log"))] if source.is_dir() else [logs_path]
    if metrics_path:
        paths.append(metrics_path)
    return run_command(
        kind="triage",
        system=_SYSTEM,
        paths=paths,
        baseline=baseline,
        metrics_file=metrics_path,
        output=output,
        local=local,
        dry_run=dry_run,
    )
