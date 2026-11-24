"""Capture minimal correlation fields from local OTLP/HTTP JSON requests."""

import json
import os
import stat
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, cast

from radea.incident_triage.telemetry import METRIC_TYPES, TRACE_ID, _hex_id, _records, span_fields

ROUTES = {
    "/v1/traces": ("traces", "resourceSpans"),
    "/v1/logs": ("logs", "resourceLogs"),
    "/v1/metrics": ("metrics", "resourceMetrics"),
}


def project(data: Any, root: str) -> dict:
    if not isinstance(data, dict) or root not in data:
        raise ValueError("Missing OTLP signal")
    if root == "resourceSpans":
        spans = []
        for span in _records(data, root, "scopeSpans", "spans"):
            trace, span_id, parent, start, end, code = span_fields(span)
            spans.append(
                {
                    "traceId": trace,
                    "spanId": span_id,
                    "parentSpanId": parent,
                    "startTimeUnixNano": str(start),
                    "endTimeUnixNano": str(end),
                    "status": {"code": code},
                }
            )
        return {root: [{"scopeSpans": [{"spans": spans}]}]}
    if root == "resourceLogs":
        records = []
        for record in _records(data, root, "scopeLogs", "logRecords"):
            trace, severity = record.get("traceId", ""), record.get("severityNumber", 0)
            if type(severity) is not int or not 0 <= severity <= 24:
                raise ValueError("Invalid log severity")
            records.append(
                {
                    "traceId": _hex_id(trace, TRACE_ID) if trace != "" else "",
                    "severityNumber": severity,
                }
            )
        return {root: [{"scopeLogs": [{"logRecords": records}]}]}

    exemplars = []
    for metric in _records(data, root, "scopeMetrics", "metrics"):
        for kind in METRIC_TYPES:
            values = metric.get(kind)
            if isinstance(values, dict):
                for entry in _records(values, "dataPoints", "exemplars"):
                    trace = entry.get("traceId", "")
                    if trace != "":
                        exemplars.append({"traceId": _hex_id(trace, TRACE_ID)})
    return {
        root: [
            {
                "scopeMetrics": [
                    {
                        "metrics": [
                            {"gauge": {"dataPoints": [{"exemplars": exemplars}]}},
                        ]
                    }
                ]
            }
        ]
    }


class CaptureServer(HTTPServer):
    def __init__(self, destination: Path, port: int, limit: int) -> None:
        self.destination = destination
        self.limit = limit
        self.batch_limit = min(limit, 1_048_576)
        super().__init__(("127.0.0.1", port), Handler)

    def append(self, signal: str, document: dict) -> bool:
        row = json.dumps(document, separators=(",", ":"), allow_nan=False).encode() + b"\n"
        path = self.destination / f"{signal}.jsonl"
        flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
        flags |= getattr(os, "O_NONBLOCK", 0)
        descriptor = os.open(path, flags, 0o600)
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode):
                raise OSError("Expected a regular capture file")
            if info.st_size + len(row) > self.limit:
                return False
            if os.write(descriptor, row) != len(row):
                os.ftruncate(descriptor, info.st_size)
                raise OSError("Incomplete capture write")
            return True
        finally:
            os.close(descriptor)


class Handler(BaseHTTPRequestHandler):
    def setup(self) -> None:
        self.request.settimeout(5)
        super().setup()

    def log_message(self, _format: str, *args: Any) -> None:
        pass

    def _respond(self, status: int, message: str | None = None) -> None:
        data = json.dumps({} if message is None else {"message": message}).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self) -> None:
        route = ROUTES.get(self.path)
        if route is None:
            self._respond(404, "Unknown OTLP signal")
            return
        if (
            self.headers.get_content_type() != "application/json"
            or self.headers.get("Content-Encoding", "identity").lower() != "identity"
            or self.headers.get("Transfer-Encoding")
        ):
            self._respond(415, "Expected uncompressed OTLP JSON")
            return
        server = cast(CaptureServer, self.server)
        lengths = self.headers.get_all("Content-Length", [])
        length = lengths[0] if len(lengths) == 1 else ""
        if not length.isascii() or not length.isdigit() or len(length) > 10:
            self._respond(400, "Expected one valid Content-Length")
            return
        size = int(length)
        if not 1 <= size <= server.batch_limit:
            self._respond(413, "Payload exceeds capture bounds")
            return
        try:
            raw = self.rfile.read(size)
            if len(raw) != size:
                raise ValueError("Incomplete request")
            document = project(json.loads(raw), route[1])
        except (ValueError, RecursionError, TimeoutError):
            self._respond(400, "Invalid OTLP batch")
            return
        try:
            stored = server.append(route[0], document)
        except OSError:
            self._respond(503, "Capture storage unavailable")
            return
        if stored:
            self._respond(200)
        else:
            self._respond(503, "Capture quota reached")
