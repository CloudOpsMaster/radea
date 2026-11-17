"""Evidence-based advisory analysis with shared runtime guardrails."""

from radea.core.runtime import run_command

_SYSTEM = """You are a senior DevOps engineer reviewing Terraform code and plan output.
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
) -> dict:
    return run_command(
        kind="iac-review",
        system=_SYSTEM,
        paths=[p for p in [tf_file, context_file] if p],
        plan_file=plan_file,
        output=output,
        local=local,
        dry_run=dry_run,
    )
