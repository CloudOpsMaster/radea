# Weighted HTTP migrations and canary releases

Use a Kubernetes Gateway with an installed Gateway API controller such as Envoy Gateway.
Deploy two Services with ready endpoints in the HTTPRoute namespace. For a migration,
keep the legacy service running while you route a path prefix to the replacement.
For a canary, point the two Services at the stable and candidate releases.

```sh
radea gateway-route --namespace apps --gateway edge --route migration \
  --stable legacy --candidate replacement --port 8080 --path-prefix /catalog \
  | kubectl --kubeconfig cluster.yaml --context staging apply -f -

radea gateway-rollout --kubeconfig cluster.yaml --context staging --namespace apps \
  --route migration --stable legacy --candidate replacement --weight 10 --apply
```

The route initially sends all traffic to legacy. The second command changes the rule
to 90/10. The weights are routing proportions. Measured shares vary across finite
samples. Use `--hostname` to scope a route on a shared Gateway. Use `--gateway-namespace`
and `--listener` to select an allowed cross-namespace attachment or specific listener.
The route renderer uses one shared Service port. You can also target an existing
HTTPRoute rule with two same-namespace Service references and independent ports.

## Prometheus and automatic changes

Use candidate-specific PromQL expressions. Edit the example to match the metric names,
labels and scrape interval from your ingress, mesh or application. Each expression
must return one scalar or one series. Set the observation window at least as long as
the range used for the queries so previous steps cannot contribute to the decision.

```json
{
  "queries": {
    "requests": "sum(increase(http_requests_total{namespace=\"apps\",service=\"replacement\"}[5m]))",
    "success_rate": "sum(increase(http_requests_total{namespace=\"apps\",service=\"replacement\",status=~\"2..|3..\"}[5m])) / sum(increase(http_requests_total{namespace=\"apps\",service=\"replacement\"}[5m]))",
    "p95_ms": "1000 * histogram_quantile(0.95, sum by (le) (rate(http_request_duration_seconds_bucket{namespace=\"apps\",service=\"replacement\"}[5m])))",
    "sample_age_seconds": "time() - max(timestamp(http_requests_total{namespace=\"apps\",service=\"replacement\"}))"
  },
  "window_seconds": 300,
  "min_requests": 100,
  "min_success_rate": 0.99,
  "max_p95_ms": 200,
  "max_sample_age_seconds": 30,
  "steps": [25, 50, 100]
}
```

```sh
radea gateway-rollout --kubeconfig cluster.yaml --context staging --namespace apps \
  --route migration --stable legacy --candidate replacement \
  --prometheus https://prometheus.internal --policy policy.json --wait-seconds 1800 --apply
```

The gate starts its observation window after it sees both `Accepted` and `ResolvedRefs`
for the current HTTPRoute generation. Passing signals advance to the next weight,
up to 100% candidate. A measured failure at sufficient volume returns traffic to stable.
Missing, stale or insufficient telemetry holds the current weights. In case of a
concurrent update, the Kubernetes resource version precondition rejects the patch.
Give the rollout identity only `get` and `patch` for the selected HTTPRoute. If GitOps
manages the route, configure it to leave the managed weights and rollout annotations
under this command's control while rollout is active.

The command reports JSON and exits with 0 for stage or promotion, 2 for rollback,
and 3 for hold or a rollout with further steps pending. Use `--weight 0 --apply`
with the same route arguments to manually return all traffic to stable. Access to
Prometheus is via its HTTP query API using a trusted internal endpoint or a local
authenticated proxy. Use explicit TLS termination and access controls on your Gateway.
For a pre-cutover smoke test use `migration-parity` with the same read-only path
against the two origins. It compares the HTTP status, media type and body, normalizes
the key order of JSON objects, and outputs only mismatch categories. Use a fixture
path with deterministic output. To rehearse with live requests, render the route with `--shadow-reads` and apply it
to a listener whose controller supports Gateway API RequestMirror and method matching.
The candidate receives copies of GET and HEAD requests for the path. The client
receives the legacy response for every method. Use an isolated candidate that can
safely receive copies of requests and their headers. The Gateway discards the shadow
response, so use `migration-parity` for independent response comparisons. Reapply the
regular manifest to remove mirroring before staging weights. Data reconciliation
depends on the application.

Reproduce the isolated integration with `tools/k8s_lab.sh --gateway`. The lab requires
Minikube, Helm, kubectl, RADEA, Python and Prometheus. It sends real requests through
Envoy Gateway and runs Prometheus against a probe exporter that reports candidate
request count and latency.

[Gateway API traffic splitting](https://gateway-api.sigs.k8s.io/guides/user-guides/traffic-splitting/)
· [Envoy Gateway metrics](https://gateway.envoyproxy.io/v1.8/tasks/observability/proxy-metric/)
· [Prometheus query API](https://prometheus.io/docs/prometheus/latest/querying/api/)

## Staging cutover rehearsal

Give the two deployments distinct response bodies on a read-only probe path.
Start with the route at 100% stable. Then run the rehearsal against that route
and the Gateway's staging address.

```sh
radea cutover-rehearse --kubeconfig cluster.yaml --context staging --namespace apps \
  --route migration --stable legacy --candidate replacement \
  --origin https://staging.example.com --path /catalog/ready \
  --stable-body legacy --candidate-body replacement --fail-at 100 --apply
```

The command samples HTTP availability at baseline and after each weight change.
By default it advances through 25%, 50%, and 100% candidate. At 100% it verifies
the candidate response marker. The rehearsal always attempts to return to 0%
candidate and confirms the stable response marker after restoration. Use
`--fail-at` to test the rollback path after a chosen stage passes. The JSON
report gives probe counts per stage, the outcome of the injected failure, and
whether restoration was verified. The command exits with 2 for a failed probe
or unconfirmed restoration. Run the rehearsal with exclusive control of the
selected staging route. A conflict or a disconnected Kubernetes API can prevent
automated restoration.

The probes cover HTTP behavior at the configured cadence. Run application-specific
load and data consistency checks separately for stateful migrations.
