"""Send synthetic OTLP signals to the Collector in the same Pod."""

import json
import struct
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

from radea.incident_triage.telemetry import analyse


def protobuf_message(field: int, payload: bytes) -> bytes:
    # The lab messages fit into a single byte length prefix.
    return bytes([(field << 3) | 2, len(payload)]) + payload


def send(signal: str, body: bytes, content_type: str) -> None:
    request = Request(
        f"http://127.0.0.1:4318/v1/{signal}", data=body, headers={"Content-Type": content_type},
    )
    for attempt in range(20):
        try:
            with urlopen(request, timeout=2) as response:
                if response.status != 200:
                    raise ValueError("Collector returned an unexpected status")
                return
        except URLError:
            if attempt == 19:
                raise
            time.sleep(0.25)


def main() -> None:
    trace = "ab" * 16
    span = protobuf_message(1, bytes.fromhex(trace)) + protobuf_message(2, b"spanabcd")
    span += protobuf_message(5, b"private-span") + struct.pack("<BQBQ", 0x39, 1000, 0x41, 2000)
    send("traces", protobuf_message(1, protobuf_message(2, protobuf_message(2, span))),
         "application/x-protobuf")
    logs = {"resourceLogs": [{"scopeLogs": [{"logRecords": [{
        "traceId": trace, "severityNumber": 17, "body": {"stringValue": "private-log"},
    }]}]}]}
    metrics = {"resourceMetrics": [{"scopeMetrics": [{"metrics": [{
        "name": "private-metric", "gauge": {"dataPoints": [{
            "timeUnixNano": "2000", "asInt": "1",
            "exemplars": [{"traceId": trace, "timeUnixNano": "2000", "asInt": "1"}],
        }]},
    }]}]}]}
    for signal, data in (("logs", logs), ("metrics", metrics)):
        send(signal, json.dumps(data).encode(), "application/json")
    signals = ("traces", "logs", "metrics")
    paths = [Path("/captures/session", f"{signal}.jsonl") for signal in signals]
    for _ in range(40):
        if all(path.exists() and path.stat().st_size for path in paths):
            break
        time.sleep(0.25)
    trace_path, log_path, metric_path = map(str, paths)
    report = analyse(trace_path, log_path, metric_path, 1_048_576)
    row = report["traces"][0]
    if (row["span_count"], row["error_logs"], row["metric_exemplars"]) != (1, 1, 1):
        raise SystemExit("Expected one matching span, error log and metric exemplar")
    if any("private-" in path.read_text() for path in paths):
        raise SystemExit("Unexpected raw telemetry in capture")
    print("Collector: correlated one Protobuf span, JSON error log and metric exemplar")


if __name__ == "__main__":
    main()
