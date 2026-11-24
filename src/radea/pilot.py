"""Compare effort and review outcomes on matched engineering pilot cases."""

import json
import math
import re
from decimal import Decimal, localcontext
from statistics import median

from radea.static_review.files import collect

TIMES = ("baseline_minutes", "assisted_minutes", "verification_minutes", "rework_minutes")
EXPENSES = ("licenses", "api_compute", "adoption", "incident_cost")
MONEY = re.compile(r"[0-9]{1,12}(?:\.[0-9]{1,6})?\Z")


def _economics(data, baseline: float, assisted: float) -> dict:
    if not isinstance(data, dict) or set(data) != {"currency", "hourly_labor_rate", *EXPENSES}:
        raise ValueError("Economics requires one currency, a labor rate and all expense categories")
    currency = data["currency"]
    if not isinstance(currency, str) or not re.fullmatch(r"[A-Z]{3}", currency):
        raise ValueError("Expected a three-letter economics currency")
    amounts = {}
    for key in ("hourly_labor_rate", *EXPENSES):
        value = data[key]
        if not isinstance(value, str) or not MONEY.fullmatch(value):
            raise ValueError(f"{key} must be a nonnegative decimal string")
        amounts[key] = Decimal(value)
    with localcontext() as context:
        context.prec = 40
        rate = amounts["hourly_labor_rate"]
        baseline_labor = Decimal(str(baseline)) * rate / 60
        assisted_labor = Decimal(str(assisted)) * rate / 60
        expenses = sum((amounts[key] for key in EXPENSES), Decimal(0))
        invested = assisted_labor + expenses
        net = baseline_labor - invested
        return {
            "currency": currency,
            "baseline_labor": format(baseline_labor, ".2f"),
            "assisted_labor": format(assisted_labor, ".2f"),
            "additional_costs": format(expenses, ".2f"),
            "net_value": format(net, ".2f"),
            "roi_percentage": format(100 * net / invested, ".2f") if invested else None,
        }


def _minutes(row: dict, field: str) -> float:
    value = row.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 1e6:
        raise ValueError(f"{field} must be a finite number between 0 and 1000000")
    return float(value)


def analyse(path: str, max_bytes: int) -> dict:
    sources, _ = collect([path], max_bytes=max_bytes)
    if len(sources) != 1:
        raise ValueError("Expected one pilot data file")
    source = sources[0]
    try:
        payload = json.loads(source.text)
    except (ValueError, RecursionError):
        raise ValueError("Invalid pilot JSON") from None
    cases = payload.get("cases") if isinstance(payload, dict) else None
    if not isinstance(cases, list) or not 1 <= len(cases) <= 10_000:
        raise ValueError("Expected 1–10000 matched pilot cases")

    seen = set()
    baseline_totals: list[float] = []
    assisted_totals: list[float] = []
    savings: list[float] = []
    accepted = 0
    missed_critical = 0
    for row in cases:
        case_id = row.get("id") if isinstance(row, dict) else None
        if not isinstance(case_id, str) or not case_id.strip() or case_id in seen:
            raise ValueError("Every case requires a unique nonempty id")
        seen.add(case_id)
        baseline, assisted, verification, rework = [_minutes(row, field) for field in TIMES]
        if baseline == 0:
            raise ValueError("Each baseline must measure positive time")
        if type(row.get("accepted")) is not bool or type(row.get("missed_critical")) is not bool:
            raise ValueError("Every case requires boolean accepted and missed_critical outcomes")
        total = math.fsum((assisted, verification, rework))
        baseline_totals.append(baseline)
        assisted_totals.append(total)
        savings.append(baseline - total)
        accepted += row["accepted"]
        missed_critical += row["missed_critical"]

    baseline_sum = math.fsum(baseline_totals)
    assisted_sum = math.fsum(assisted_totals)
    speedup = baseline_sum / assisted_sum if assisted_sum else None
    report = {
        "schema_version": "1.0",
        "command": "pilot-report",
        "source": source.meta(),
        "cases": len(cases),
        "baseline_minutes": baseline_sum,
        "assisted_total_minutes": assisted_sum,
        "net_minutes_saved": math.fsum(savings),
        "median_case_minutes_saved": median(savings),
        "speedup": speedup if speedup is not None and math.isfinite(speedup) else None,
        "accepted": accepted,
        "missed_critical": missed_critical,
    }
    if "economics" in payload:
        report["economics"] = _economics(payload["economics"], baseline_sum, assisted_sum)
    return report
