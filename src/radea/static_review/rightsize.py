"""Resource right-sizing from observed usage percentiles (articles 14, 17, 77, 78).

Averages hide bursts, so recommendations come from p95 CPU and p99/max memory with explicit
headroom. The numbers are advice with their derivation shown; they are never applied.
"""

import json
import math
from typing import Any

from radea.static_review.files import Source
from radea.static_review.findings import Finding, quote
from radea.static_review.k8s import quantity

CPU_HEADROOM = 1.15
MEMORY_HEADROOM = 1.20
LIMIT_HEADROOM = 1.30
OVERSIZED = 2.0
MIB = 2**20


def _round_up(value: float, step: float) -> float:
    return math.ceil(value / step) * step


def _cpu(value: float) -> str:
    return f"{round(value * 1000)}m"


def _mem(value: float) -> str:
    return f"{math.ceil(value / MIB)}Mi"


def parse_usage(src: Source) -> list[dict[str, Any]]:
    try:
        data = json.loads(src.text)
    except ValueError:
        raise ValueError("not valid JSON") from None
    if isinstance(data, dict) and isinstance(data.get("containers"), list):
        data = data["containers"]
    if not isinstance(data, list) or not data:
        raise ValueError("expected a JSON list of container usage records")
    return [item for item in data if isinstance(item, dict)]


def analyse(src: Source) -> tuple[list[Finding], list[dict], list[dict]]:
    findings: list[Finding] = []
    recommendations: list[dict] = []
    skipped: list[dict] = []
    for index, item in enumerate(parse_usage(src)):
        target = f"{item.get('workload', '?')}/{item.get('container', '?')}"
        cpu, mem = item.get("cpu") or {}, item.get("memory") or {}
        cpu95 = quantity(cpu.get("p95"))
        mem99 = quantity(mem.get("p99", mem.get("max")))
        mem_max = quantity(mem.get("max", mem.get("p99")))
        if cpu95 is None or mem99 is None or mem_max is None or mem_max < mem99:
            skipped.append({"path": f"{src.path}#{index}", "reason": f"{target}: incomplete usage"})
            continue
        reqs, limits = item.get("requests") or {}, item.get("limits") or {}
        want_cpu = max(_round_up(cpu95 * CPU_HEADROOM, 0.01), 0.01)
        want_mem = _round_up(mem99 * MEMORY_HEADROOM, 16 * MIB)
        want_limit = max(_round_up(mem_max * LIMIT_HEADROOM, 16 * MIB), want_mem)
        recommendations.append(
            {
                "workload": item.get("workload"),
                "container": item.get("container"),
                "cpu_request": _cpu(want_cpu),
                "memory_request": _mem(want_mem),
                "memory_limit": _mem(want_limit),
                "basis": f"cpu p95 x{CPU_HEADROOM}, memory p99 x{MEMORY_HEADROOM}, "
                f"limit max x{LIMIT_HEADROOM}",
            }
        )

        def emit(rule: str, detail: str, evidence: str, _target: str = target) -> None:
            findings.append(Finding(rule, _target, src.path, None, quote(evidence), detail))

        cpu_req, mem_req = quantity(reqs.get("cpu")), quantity(reqs.get("memory"))
        mem_lim = quantity(limits.get("memory"))
        if cpu_req is not None and cpu_req < cpu95:
            emit(
                "RS001",
                f"recommend {_cpu(want_cpu)}",
                f"request {_cpu(cpu_req)}, p95 {_cpu(cpu95)}",
            )
        elif cpu_req is not None and cpu_req > OVERSIZED * want_cpu and cpu_req - want_cpu >= 0.1:
            emit("RS004", f"cpu: recommend {_cpu(want_cpu)}", f"request {_cpu(cpu_req)}")
        if mem_req is not None and mem_req < mem99:
            emit(
                "RS002",
                f"recommend {_mem(want_mem)}",
                f"request {_mem(mem_req)}, p99 {_mem(mem99)}",
            )
        elif (
            mem_req is not None
            and mem_req > OVERSIZED * want_mem
            and mem_req - want_mem >= 64 * MIB
        ):
            emit("RS004", f"memory: recommend {_mem(want_mem)}", f"request {_mem(mem_req)}")
        if mem_lim is not None and mem_lim < mem_max * 1.1:
            emit(
                "RS003",
                f"recommend {_mem(want_limit)}",
                f"limit {_mem(mem_lim)}, max {_mem(mem_max)}",
            )
    return findings, recommendations, skipped
