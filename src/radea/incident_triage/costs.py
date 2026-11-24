"""Attribute costs in a local FOCUS-shaped CSV export without mixing currencies."""

import csv
import io
import json
import re
from collections import defaultdict
from decimal import Decimal, localcontext

from radea.core.sanitizer import clean
from radea.static_review.files import collect

CURRENCY = re.compile(r"[A-Z]{3}\Z")
AMOUNT = re.compile(r"[+-]?[0-9]{1,18}(?:\.[0-9]{1,18})?\Z")


def allocate(path: str, dimensions: tuple[str, ...], tag: str | None, limit: int) -> dict:
    return clean(_allocate(path, dimensions, tag, limit))


def _allocate(path: str, dimensions: tuple[str, ...], tag: str | None, limit: int) -> dict:
    sources, _ = collect([path], max_bytes=limit)
    if len(sources) != 1:
        raise ValueError("Expected one billing CSV export")
    source = sources[0]
    csv_file = csv.DictReader(io.StringIO(source.text.removeprefix("\ufeff")), strict=True)
    required = {"BilledCost", "BillingCurrency", *dimensions}
    if tag is not None:
        required.add("Tags")
    sums: dict[tuple[str, tuple[str | None, ...]], Decimal] = defaultdict(Decimal)
    totals: dict[str, Decimal] = defaultdict(Decimal)
    count = unattributed = 0
    try:
        fields = csv_file.fieldnames or []
        if not required.issubset(fields) or len(fields) != len(set(fields)):
            raise ValueError("Billing CSV is missing required columns or has duplicate headers")
        with localcontext() as context:
            context.prec = 50
            for row in csv_file:
                if None in row or any(row.get(key) is None for key in required):
                    raise ValueError(f"Malformed billing row ending at line {csv_file.line_num}")
                currency, cost = row["BillingCurrency"], row["BilledCost"]
                if not CURRENCY.fullmatch(currency) or not AMOUNT.fullmatch(cost):
                    raise ValueError(f"Invalid currency or amount at line {csv_file.line_num}")
                values = tuple(row[name] or None for name in dimensions)
                if tag is not None:
                    tags = json.loads(row["Tags"]) if row["Tags"] else {}
                    value = tags.get(tag) if isinstance(tags, dict) else None
                    if not isinstance(tags, dict) or (
                        value is not None and not isinstance(value, str)
                    ):
                        raise ValueError(f"Invalid tags at line {csv_file.line_num}")
                    values += (value or None,)
                amount = Decimal(cost)
                sums[currency, values] += amount
                totals[currency] += amount
                count += 1
                unattributed += None in values
    except (csv.Error, json.JSONDecodeError, RecursionError):
        raise ValueError(f"Invalid billing export near line {csv_file.line_num}") from None
    if not count:
        raise ValueError("Billing export has no data rows")
    names = [*dimensions, *([f"tag:{tag}"] if tag is not None else [])]
    return {
        "schema_version": "1.0",
        "command": "cost-report",
        "source": source.meta(),
        "rows": count,
        "unattributed_rows": unattributed,
        "totals": {key: format(value, "f") for key, value in sorted(totals.items())},
        "allocations": [
            {
                "currency": currency,
                "dimensions": dict(zip(names, values, strict=True)),
                "billed_cost": format(value, "f"),
            }
            for (currency, values), value in sorted(
                sums.items(),
                key=lambda entry: (entry[0][0], tuple(v or "" for v in entry[0][1])),
            )
        ],
    }


def compare(
    baseline: str, current: str, dimensions: tuple[str, ...], tag: str | None, limit: int,
) -> dict:
    if baseline == current == "-":
        raise ValueError("Only one billing export may use stdin")
    before, after = (_allocate(path, dimensions, tag, limit) for path in (baseline, current))
    groups = []
    for report in (before, after):
        groups.append({
            (row["currency"], tuple(row["dimensions"].values())): Decimal(row["billed_cost"])
            for row in report["allocations"]
        })
    old, new = groups
    names = (*dimensions, *((f"tag:{tag}",) if tag is not None else ()))
    changes = []
    with localcontext() as context:
        context.prec = 50
        for currency, values in sorted(
            old.keys() | new.keys(),
            key=lambda key: (key[0], tuple(value or "" for value in key[1])),
        ):
            baseline_amount = old.get((currency, values))
            current_amount = new.get((currency, values))
            delta = (current_amount or Decimal(0)) - (baseline_amount or Decimal(0))
            if delta == 0 and baseline_amount is not None and current_amount is not None:
                continue
            changes.append({
                "currency": currency,
                "dimensions": dict(zip(names, values, strict=True)),
                "baseline": format(baseline_amount, "f") if baseline_amount is not None else None,
                "current": format(current_amount, "f") if current_amount is not None else None,
                "delta": format(delta, "f"),
            })
    return clean({
        "schema_version": "1.0",
        "command": "cost-report",
        "baseline": {key: before[key] for key in ("source", "rows", "totals", "unattributed_rows")},
        "current": {key: after[key] for key in ("source", "rows", "totals", "unattributed_rows")},
        "changes": changes,
    })
