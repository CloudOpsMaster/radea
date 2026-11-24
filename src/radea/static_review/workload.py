"""Map explicit workload requirements to a Kubernetes controller recommendation."""


def choose(
    per_node: bool,
    stable_identity: bool,
    per_pod_storage: bool,
    ordered: bool,
    finite: bool,
    scheduled: bool,
) -> dict:
    stateful = stable_identity or per_pod_storage or ordered
    batch = finite or scheduled
    if sum((stateful, batch, per_node)) > 1:
        raise ValueError(
            "Requirements combine node affinity, stateful ordering or batch execution; "
            "split the workloads or review the architecture"
        )
    if scheduled:
        kind, reason = "CronJob", "Run the finite workload on a schedule"
    elif finite:
        kind, reason = "Job", "Run the workload to completion"
    elif per_node:
        kind, reason = "DaemonSet", "Run one instance per matching node"
    elif stateful:
        kind, reason = "StatefulSet", "Keep identity, per-Pod storage or ordered operations"
    else:
        kind, reason = "Deployment", "Run interchangeable long-lived replicas"
    return {
        "schema_version": "1.0",
        "command": "k8s-workload-plan",
        "kind": kind,
        "reason": reason,
        "draft": True,
    }
