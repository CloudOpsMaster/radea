"""Evidence-based advisory analysis with shared runtime guardrails."""

from radea.core.runtime import run_command

_SYSTEM = """You are a senior DevOps engineer triaging a failing CI build.
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
) -> dict:
    return run_command(
        kind="debug",
        system=_SYSTEM,
        paths=[log_path],
        sanitize_input=sanitize_input,
        output=output,
        local=local,
        dry_run=dry_run,
    )
