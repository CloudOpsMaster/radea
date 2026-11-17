"""Offline resource acceptance: Linux enforces 256 MiB address space and one CPU."""

import argparse
import json
import os
import resource
import sys
import tempfile
import time
from pathlib import Path

from radea.api import AnalysisRequest, Config, analyze


def benchmark() -> dict:
    constrained = sys.platform == "linux"
    if constrained:
        resource.setrlimit(resource.RLIMIT_AS, (256 * 1024 * 1024, 256 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_CPU, (30, 30))
        cpus = os.sched_getaffinity(0)
        os.sched_setaffinity(0, {min(cpus)})
    with tempfile.TemporaryDirectory(prefix="radea-resource-") as directory:
        path = Path(directory) / "large.log"
        chunk = b"INFO routine operation completed\n" * 256
        with path.open("wb") as stream:
            while stream.tell() < 6 * 1024 * 1024:
                stream.write(chunk)
            stream.write(b"FATAL acceptance-tail-failure\n")
        started = time.monotonic()
        result = analyze(
            AnalysisRequest(command="debug", paths=(str(path),), dry_run=True),
            config=Config(audit_dir=str(Path(directory) / "audit")),
        )
        elapsed = time.monotonic() - started
        if result.get("error"):
            raise RuntimeError(result["error"])
        assert "FATAL acceptance-tail-failure" in result["evidence"].values()
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        rss_mib = rss / (1024 * 1024 if sys.platform == "darwin" else 1024)
        assert rss_mib < 128, f"Peak RSS exceeded 128 MiB: {rss_mib}"
        return {
            "mode": "offline_resource_acceptance",
            "platform": sys.platform,
            "limits_enforced": constrained,
            "address_space_limit_mib": 256 if constrained else None,
            "cpu_affinity_count": len(os.sched_getaffinity(0)) if constrained else None,
            "input_bytes": path.stat().st_size,
            "peak_rss_mib": round(rss_mib, 2),
            "elapsed_seconds": round(elapsed, 3),
            "payload_chars": result["payload_chars"],
            "omitted_lines": result["sources"][0]["omitted_lines"],
            "tail_preserved": True,
            "inference_calls": 0,
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = benchmark()
    encoded = json.dumps(result, indent=2) + "\n"
    if args.output:
        args.output.write_text(encoded)
    print(encoded, end="")


if __name__ == "__main__":
    main()
