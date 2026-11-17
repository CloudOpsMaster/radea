"""Shared Rich output helpers for all RADEA commands."""

from __future__ import annotations

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

console = Console()

SEVERITY_ICON = {"high": "🔴", "medium": "🟡", "low": "🟢", "info": "ℹ️ "}
SEVERITY_COLOR = {"high": "red", "medium": "yellow", "low": "green", "info": "blue"}
CONFIDENCE_COLOR = {"high": "green", "medium": "yellow", "low": "red"}


def header(title: str, subtitle: str = "") -> None:
    t = Text()
    t.append("RADEA", style="bold cyan")
    t.append(f" · {title}", style="bold white")
    if subtitle:
        t.append(f"\n{subtitle}", style="dim")
    console.print(Panel(t, border_style="cyan", padding=(0, 2)))


def draft_warning() -> None:
    console.print(
        Panel(
            "[yellow]⚠  AI DRAFT — verify every item before acting.[/]",
            border_style="yellow",
            padding=(0, 2),
        )
    )


def sanitizer_line(redactions: int) -> None:
    if redactions:
        console.print(f"[dim]Sanitizer:[/] [yellow]{redactions} redaction(s) applied[/]")
    else:
        console.print("[dim]Sanitizer: clean[/]")


def hypotheses_table(hypotheses: list[dict]) -> None:
    table = Table(box=box.ROUNDED, border_style="cyan", show_header=True, header_style="bold cyan")
    table.add_column("#", style="dim", width=3)
    table.add_column("Cause", style="white", min_width=24)
    table.add_column("Confidence", justify="center", width=10)
    table.add_column("Description")
    table.add_column("Verify", style="dim")

    for i, h in enumerate(hypotheses, 1):
        conf = h.get("confidence", "low")
        table.add_row(
            str(i),
            f"[bold]{h['title']}[/]",
            f"[{CONFIDENCE_COLOR.get(conf, 'white')}]{conf}[/]",
            h.get("description", ""),
            h.get("verify", ""),
        )
    console.print(table)


def findings_table(findings: list[dict]) -> None:
    table = Table(box=box.ROUNDED, border_style="cyan", show_header=True, header_style="bold cyan")
    table.add_column("", width=3)
    table.add_column("Finding", style="white", min_width=24)
    table.add_column("Resource", style="dim")
    table.add_column("Description")

    for f in findings:
        sev = f.get("severity", "info")
        table.add_row(
            SEVERITY_ICON.get(sev, "ℹ️ "),
            f"[{SEVERITY_COLOR.get(sev, 'white')} bold]{f['title']}[/]",
            f.get("resource", ""),
            f.get("description", ""),
        )
    console.print(table)


def destructive_banner(actions: list[dict]) -> None:
    lines = ["[bold red]STOP — Destructive actions in this plan[/]\n"]
    for a in actions:
        lines.append(f"  [red]✗[/]  [bold]{a['resource']}[/]  →  [red]{a['action']}[/]")
    console.print(Panel("\n".join(lines), border_style="red", padding=(0, 2)))


def patterns_table(patterns: list[dict]) -> None:
    table = Table(box=box.ROUNDED, border_style="cyan", show_header=True, header_style="bold cyan")
    table.add_column("", width=3)
    table.add_column("Pattern", style="white", min_width=20)
    table.add_column("Count", justify="right", width=7)
    table.add_column("Example line", style="dim")
    table.add_column("Description")

    for p in patterns:
        sev = p.get("severity", "low")
        table.add_row(
            SEVERITY_ICON.get(sev, "🟢"),
            f"[bold]{p['label']}[/]",
            str(p.get("count", "?")),
            p.get("example_line", ""),
            p.get("description", ""),
        )
    console.print(table)


def timeline_table(events: list[dict]) -> None:
    table = Table(box=box.SIMPLE, border_style="dim", show_header=True, header_style="bold cyan")
    table.add_column("Time", style="cyan", width=8)
    table.add_column("Event", style="white")
    table.add_column("Source line", style="dim")

    for e in events:
        table.add_row(e.get("time", ""), e.get("event", ""), e.get("source_line", ""))
    console.print(table)
