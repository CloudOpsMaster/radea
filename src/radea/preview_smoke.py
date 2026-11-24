"""Run HTTP assertions against an owned preview through a loopback port-forward."""

import re
import subprocess
import time
from pathlib import Path
from tempfile import TemporaryDirectory

from radea.kube_smoke import check
from radea.preview import _namespace, _target, identity

FORWARDING = re.compile(rb"^Forwarding from 127\.0\.0\.1:(\d{1,5}) -> ", re.MULTILINE)


def probe(
    project: str, pr: int, kubeconfig: str, context: str, port: int, cases: str, limit: int,
) -> dict:
    namespace, labels = identity(project, pr)
    target = _target(kubeconfig, context)
    metadata = _namespace(target, namespace, labels)
    if metadata is None or metadata.get("deletionTimestamp"):
        raise ValueError("Expected an active, owned preview namespace")
    with TemporaryDirectory(prefix="radea-preview-") as work:
        log = Path(work) / "forward.log"
        with log.open("wb") as forwarded:
            process = subprocess.Popen(
                [
                    *target, "--namespace", namespace, "port-forward", "--address", "127.0.0.1",
                    "--pod-running-timeout=12s", "service/app", f":{port}",
                ],
                stdin=subprocess.DEVNULL, stdout=forwarded, stderr=subprocess.STDOUT,
            )
        try:
            deadline = time.monotonic() + 15
            while process.poll() is None and time.monotonic() < deadline:
                with log.open("rb") as forwarded:
                    match = FORWARDING.search(forwarded.read(8192))
                if match:
                    origin = f"http://127.0.0.1:{match[1].decode()}"
                    return check(cases, origin, kubeconfig, context, namespace, "app", limit)
                time.sleep(0.1)
            raise ValueError("Preview Service port-forward did not become ready")
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
