"""Capture request outcomes for the disposable Minikube canary lab."""

import argparse
import json
import subprocess
import time


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--context", required=True)
    parser.add_argument("--path", choices=("ready", "missing"), required=True)
    args = parser.parse_args()
    requests = []
    for _ in range(8):
        started = time.monotonic()
        try:
            response = subprocess.run(
                [
                    "kubectl",
                    "--context",
                    args.context,
                    "--namespace",
                    "radea-lab",
                    "exec",
                    "deploy/radea-lab",
                    "--",
                    "wget",
                    "-T",
                    "3",
                    "-qO-",
                    f"http://radea-preview:8080/{args.path}",
                ],
                capture_output=True,
                check=False,
                timeout=8,
            )
            if response.returncode == 0 and response.stdout == b"radea-preview":
                requests.append({"ok": True, "latency_ms": (time.monotonic() - started) * 1000})
            else:
                requests.append({"ok": False})
        except subprocess.TimeoutExpired:
            requests.append({"ok": False})
    print(json.dumps({"requests": requests}))


if __name__ == "__main__":
    main()
