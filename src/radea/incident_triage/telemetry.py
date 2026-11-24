"""Correlate captured OTLP spans, log records and metric exemplars by trace ID."""

import json
import re
from collections import Counter
from collections.abc import Iterator
from typing import Any

from radea.core.sanitizer import clean
from radea.static_review.files import Source, collect

TRACE_ID = re.compile(r"[0-9a-fA-F]{32}\Z")
SPAN_ID = re.compile(r"[0-9a-fA-F]{16}\Z")
METRIC_TYPES = ("gauge", "sum", "histogram", "exponentialHistogram", "summary")


def _source(path: str, limit: int) -> Source:
    sources, _ = collect([path], max_bytes=limit)
    if len(sources) != 1:
        raise ValueError("Expected one OTLP capture per signal")
    return sources[0]


def _batches(source: Source, root: str) -> Iterator[dict]:
    try:
        document = json.loads(source.text)
    except json.JSONDecodeError:
        seen = False
        for line in source.lines:
            if not line.strip():
                continue
            try:
                batch = json.loads(line)
            except (ValueError, RecursionError):
                raise ValueError("Invalid OTLP JSON or JSON Lines") from None
            if not isinstance(batch, dict) or root not in batch:
                raise ValueError(f"Expected OTLP {root} batches")
            seen = True
            yield batch
        if not seen:
            raise ValueError(f"Expected OTLP {root} batches")
    except (ValueError, RecursionError):
        raise ValueError("Invalid OTLP JSON") from None
    else:
        if not isinstance(document, dict) or root not in document:
            raise ValueError(f"Expected OTLP {root} batches")
        yield document


def _records(value: dict, *fields: str) -> Iterator[dict]:
    field, *rest = fields
    entries = value.get(field, [])
    if not isinstance(entries, list) or not all(isinstance(entry, dict) for entry in entries):
        raise ValueError(f"Invalid OTLP {field} records")
    for entry in entries:
        if rest:
            yield from _records(entry, *rest)
        else:
            yield entry


def _hex_id(value: Any, pattern: re.Pattern[str]) -> str:
    if not isinstance(value, str) or not pattern.fullmatch(value) or not int(value, 16):
        raise ValueError("Invalid OTLP trace or span ID")
    return value.lower()


def _timestamp(value: Any) -> int:
    if isinstance(value, str) and re.fullmatch(r"[0-9]{1,20}", value):
        value = int(value)
    if type(value) is not int or not 0 <= value < 2**64:
        raise ValueError("Invalid OTLP timestamp")
    return value


def span_fields(span: dict) -> tuple[str, str, str, int, int, int]:
    trace_id = _hex_id(span.get("traceId"), TRACE_ID)
    span_id = _hex_id(span.get("spanId"), SPAN_ID)
    parent = span.get("parentSpanId", "")
    if parent != "":
        parent = _hex_id(parent, SPAN_ID)
    start = _timestamp(span.get("startTimeUnixNano"))
    end = _timestamp(span.get("endTimeUnixNano"))
    if end < start or parent == span_id:
        raise ValueError("Span has invalid timing or parent")
    status = span.get("status", {})
    code = status.get("code", 0) if isinstance(status, dict) else None
    if type(code) is not int or code not in (0, 1, 2):
        raise ValueError("Invalid OTLP span status")
    return trace_id, span_id, parent, start, end, code


def analyse(traces: str, logs: str | None, metrics: str | None, limit: int) -> dict:
    sources = {"traces": _source(traces, limit)}
    spans: dict[str, dict[str, tuple[str, int, int, bool]]] = {}
    span_count = 0
    for batch in _batches(sources["traces"], "resourceSpans"):
        for span in _records(batch, "resourceSpans", "scopeSpans", "spans"):
            trace_id, span_id, parent, start, end, code = span_fields(span)
            trace = spans.setdefault(trace_id, {})
            entry = parent, start, end, code == 2
            if span_id in trace:
                if trace[span_id] != entry:
                    raise ValueError("Conflicting duplicate span")
                continue
            trace[span_id] = entry
            span_count += 1
            if span_count > 20_000:
                raise ValueError("Trace capture exceeds 20000 distinct spans")
    if not spans:
        raise ValueError("No spans to review")

    log_counts: Counter[str] = Counter()
    errors: Counter[str] = Counter()
    exemplars: Counter[str] = Counter()
    unlinked_logs = 0
    if logs is not None:
        sources["logs"] = _source(logs, limit)
        for batch in _batches(sources["logs"], "resourceLogs"):
            for record in _records(batch, "resourceLogs", "scopeLogs", "logRecords"):
                trace_id = record.get("traceId", "")
                if trace_id == "":
                    unlinked_logs += 1
                    continue
                trace_id = _hex_id(trace_id, TRACE_ID)
                level = record.get("severityNumber", 0)
                if type(level) is not int or not 0 <= level <= 24:
                    raise ValueError("Invalid OTLP log severity")
                log_counts[trace_id] += 1
                errors[trace_id] += level >= 17
    if metrics is not None:
        sources["metrics"] = _source(metrics, limit)
        for batch in _batches(sources["metrics"], "resourceMetrics"):
            for metric in _records(batch, "resourceMetrics", "scopeMetrics", "metrics"):
                for kind in METRIC_TYPES:
                    data = metric.get(kind)
                    if not isinstance(data, dict):
                        continue
                    for exemplar in _records(data, "dataPoints", "exemplars"):
                        trace_id = exemplar.get("traceId", "")
                        if trace_id != "":
                            exemplars[_hex_id(trace_id, TRACE_ID)] += 1

    findings = []
    for trace_id, trace in spans.items():
        window_ns = max(item[2] for item in trace.values()) - min(
            item[1] for item in trace.values()
        )
        findings.append(
            {
                "trace_id": trace_id,
                "span_count": len(trace),
                "error_spans": sum(item[3] for item in trace.values()),
                "missing_parent_spans": sum(
                    bool(item[0]) and item[0] not in trace for item in trace.values()
                ),
                "observed_span_window_ms": window_ns / 1_000_000,
                "logs": log_counts[trace_id],
                "error_logs": errors[trace_id],
                "metric_exemplars": exemplars[trace_id],
            }
        )
    return clean(
        {
            "schema_version": "1.0",
            "command": "telemetry-review",
            "sources": {key: source.meta() for key, source in sources.items()},
            "logs_without_trace_id": unlinked_logs,
            "logs_without_matching_trace": sum(
                count for key, count in log_counts.items() if key not in spans
            ),
            "exemplars_without_matching_trace": sum(
                count for key, count in exemplars.items() if key not in spans
            ),
            "traces": sorted(findings, key=lambda item: item["trace_id"]),
        }
    )
