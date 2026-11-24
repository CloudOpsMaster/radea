"""Exercise weighted traffic and metric-based decisions in the isolated Gateway lab."""

import json
import os
import re
import socket
import subprocess
import sys
import time
from collections import Counter, deque
from contextlib import ExitStack
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.request import urlopen


def port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def eventually(action, timeout=90):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            value = action()
            if value:
                return value
        except OSError:
            pass
        time.sleep(0.5)
    raise RuntimeError(f"Timed out waiting for {action.__name__}")


def read(url):
    with urlopen(url, timeout=3) as response:
        return response.read().decode().strip()


def stop(process):
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def main():
    context, directory = sys.argv[1:]
    work = Path(directory)
    kube = ["kubectl", "--kubeconfig", os.environ["KUBECONFIG"], "--context", context]
    route = [
        "radea",
        "gateway-rollout",
        "--kubeconfig",
        os.environ["KUBECONFIG"],
        "--context",
        context,
        "--namespace",
        "radea-lab",
        "--route",
        "migration",
        "--stable",
        "stable",
        "--candidate",
        "candidate",
        "--apply",
    ]
    selector = (
        "gateway.envoyproxy.io/owning-gateway-namespace=radea-lab,"
        "gateway.envoyproxy.io/owning-gateway-name=edge"
    )
    edge_port, prom_port = port(), port()
    edge = f"http://127.0.0.1:{edge_port}/ready"
    prom = f"http://127.0.0.1:{prom_port}"
    observations = deque(maxlen=10000)

    class Metrics(BaseHTTPRequestHandler):
        def do_GET(self):
            now = time.time()
            samples = [(ts, ms) for ts, ms in observations.copy() if now - ts <= 5]
            if samples:
                latency = sorted(ms for _, ms in samples)
                data = (
                    f"lab_candidate_requests {len(samples)}\n"
                    "lab_candidate_success_ratio 1\n"
                    f"lab_candidate_p95_ms {latency[int((len(latency) - 1) * 0.95)]}\n"
                    f"lab_candidate_last_request_seconds {samples[-1][0]}\n"
                )
            else:
                data = "lab_candidate_requests 0\n"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4")
            self.end_headers()
            self.wfile.write(data.encode())

        def log_message(self, *args):
            pass

    def send():
        start = time.time()
        backend = read(edge)
        if backend == "candidate":
            observations.append((time.time(), (time.time() - start) * 1000))
        return backend

    def check_weights(expected, requests=120):
        def sample():
            counts = Counter(send() for _ in range(requests))
            candidate = counts["candidate"] / requests
            if set(counts) <= {"stable", "candidate"} and abs(candidate - expected) <= (
                0.12 if 0 < expected < 1 else 0
            ):
                print(
                    f"Gateway target {expected:.0%} candidate, observed {dict(counts)}", flush=True
                )
                return True
            return False

        eventually(sample)

    def stage(weight):
        subprocess.run([*route, "--weight", str(weight)], check=True)

    def decision(max_latency, expected, exit_code):
        policy = work / "gateway-policy.json"
        policy.write_text(
            json.dumps(
                {
                    "queries": {
                        "requests": "lab_candidate_requests",
                        "success_rate": "lab_candidate_success_ratio",
                        "p95_ms": "lab_candidate_p95_ms",
                        "sample_age_seconds": "time() - lab_candidate_last_request_seconds",
                    },
                    "window_seconds": 5,
                    "min_requests": 5,
                    "min_success_rate": 0.99,
                    "max_p95_ms": max_latency,
                    "max_sample_age_seconds": 3,
                    "steps": [50, 100],
                }
            )
        )
        with subprocess.Popen(
            [*route, "--prometheus", prom, "--policy", str(policy), "--wait-seconds", "45"],
            stdout=subprocess.PIPE,
            text=True,
        ) as process:
            try:
                while process.poll() is None:
                    try:
                        send()
                    except OSError:
                        pass
                    time.sleep(0.035)
                output, _ = process.communicate()
            finally:
                if process.poll() is None:
                    stop(process)
        print(output, flush=True)
        report = json.loads(output)
        assert process.returncode == exit_code and report["decision"] == expected
        assert report["applied"] and report["metrics"]["requests"] >= 5
        assert report["applied_steps"] == ([50, 100] if expected == "promote" else [0])

    namespace = [*kube, "-n", "envoy-gateway-system"]
    service = eventually(
        lambda: subprocess.check_output(
            [*namespace, "get", "svc", "-l", selector, "-o", "name"], text=True
        ).strip()
    )
    if not re.fullmatch(r"service/[a-z0-9-]+", service):
        raise RuntimeError(f"Expected one Gateway Service, got {service}")

    with ExitStack() as stack:
        forward = None
        forward_log = stack.enter_context((work / "gateway-forward.log").open("w"))

        def edge_ready():
            nonlocal forward
            if forward is None or forward.poll() is not None:
                forward = subprocess.Popen(
                    [
                        *namespace,
                        "port-forward",
                        "--address",
                        "127.0.0.1",
                        service,
                        f"{edge_port}:80",
                    ],
                    stdout=forward_log,
                    stderr=subprocess.STDOUT,
                )
                stack.callback(stop, forward)
                time.sleep(0.5)
            return read(edge) == "stable"

        eventually(edge_ready)
        server = stack.enter_context(ThreadingHTTPServer(("127.0.0.1", 0), Metrics))
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        stack.callback(server.shutdown)
        config = work / "prometheus.yml"
        config.write_text(
            "global:\n  scrape_interval: 1s\nscrape_configs:\n"
            "- job_name: gateway-lab\n  static_configs:\n"
            f"  - targets: ['127.0.0.1:{server.server_port}']\n"
        )
        prometheus = subprocess.Popen(
            [
                "prometheus",
                f"--config.file={config}",
                f"--storage.tsdb.path={work / 'prometheus'}",
                f"--web.listen-address=127.0.0.1:{prom_port}",
            ]
        )
        stack.callback(stop, prometheus)
        eventually(lambda: read(f"{prom}/-/ready"))
        stage(25)
        check_weights(0.25)
        decision(3000, "promote", 0)
        check_weights(1)
        stage(25)
        check_weights(0.25)
        decision(0, "rollback", 2)
        check_weights(0)
        report = json.loads(
            subprocess.check_output(
                [
                    "radea",
                    "cutover-rehearse",
                    *route[2:],
                    "--origin",
                    f"http://127.0.0.1:{edge_port}",
                    "--path",
                    "/ready",
                    "--stable-body",
                    "stable",
                    "--candidate-body",
                    "candidate",
                    "--fail-at",
                    "100",
                ],
                text=True,
            )
        )
        print(json.dumps(report, indent=2), flush=True)
        assert report["restored"] and report["injected_failure"]
        check_weights(0)


if __name__ == "__main__":
    main()
