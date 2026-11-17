"""Presentation adapter. The analysis API never prints."""

import json


def render(result, output):
    if output == "json":
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return
    from radea.core import output as ui

    ui.header(result["command"])
    if result.get("destructive_actions"):
        ui.destructive_banner(result["destructive_actions"])
    if result.get("error"):
        ui.console.print(result["error"], markup=False, style="red")
    else:
        # Literal text prevents model-generated Rich markup from hiding warnings.
        ui.console.print(json.dumps(result, indent=2, ensure_ascii=False), markup=False)
    ui.draft_warning(offline=result.get("analysis_origin") == "deterministic_rules")
