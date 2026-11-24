import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from urllib.parse import parse_qs, urlsplit

import pytest

from radea import gateway_rollout as gateway


@pytest.mark.parametrize(
    ("success", "age", "steps", "expected", "weight"),
    [
        (1, 0, [50, 100], "advance", 50),
        (1, 0, [100], "promote", 100),
        (0.8, 0, [100], "rollback", 0),
        (1, 99, [100], "hold", None),
    ],
)
def test_apply_gateway_decision(monkeypatch, tmp_path, success, age, steps, expected, weight):
    document = gateway.emit_route("apps", "route", "edge", "stable", "candidate", 80, 25, "/slice")
    document["metadata"].update(
        resourceVersion="19",
        generation=3,
        annotations={"radea.dev/canary-started-0": "800", "radea.dev/canary-observed-0": "3:900"},
    )
    conditions = [
        {"type": name, "status": "True", "observedGeneration": 3}
        for name in ("Accepted", "ResolvedRefs")
    ]
    document["status"] = {"parents": [{"parentRef": {"name": "edge"}, "conditions": conditions}]}
    document["spec"]["rules"].append({"backendRefs": [{"name": "other"}]})
    patches = []

    def kubectl(target, *args):
        assert target[-2:] == ["--namespace", "apps"]
        if args[0] == "get":
            return json.dumps(document)
        patches.append(json.loads(args[-1]))
        return "{}"

    monkeypatch.setattr(gateway, "_kubectl", kubectl)
    monkeypatch.setattr(gateway.time, "time", lambda: 1000)
    signals = dict(zip(gateway.SIGNALS, (125, success, 25, age), strict=True))
    evaluated = []

    class Prometheus(BaseHTTPRequestHandler):
        def do_GET(self):
            query = parse_qs(urlsplit(self.path).query)
            evaluated.append(query["time"][0])
            payload = json.dumps(
                {
                    "status": "success",
                    "data": {
                        "resultType": "vector",
                        "result": [{"value": [1000, str(signals[query["query"][0]])]}],
                    },
                }
            )
            self.send_response(200)
            self.end_headers()
            self.wfile.write(payload.encode())

    config = tmp_path / "policy.json"
    config.write_text(
        json.dumps(
            {
                "queries": {key: key for key in signals},
                "window_seconds": 10,
                "min_requests": 100,
                "min_success_rate": 0.99,
                "max_p95_ms": 50,
                "max_sample_age_seconds": 5,
                "steps": steps,
            }
        )
    )
    kubeconfig = tmp_path / "kubeconfig"
    kubeconfig.touch()
    with ThreadingHTTPServer(("127.0.0.1", 0), Prometheus) as server:
        worker = Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            report = gateway.rollout(
                str(kubeconfig),
                "isolated",
                "apps",
                "route",
                "stable",
                "candidate",
                0,
                None,
                f"http://127.0.0.1:{server.server_port}",
                gateway.load_policy(str(config), 10000),
                True,
            )
        finally:
            server.shutdown()
            worker.join()

    assert report["decision"] == expected
    assert report["candidate_weight"] == weight
    assert evaluated == ["1000"] * 4
    if weight is None:
        assert not patches
    else:
        (patch,) = patches
        assert patch[0] == {"op": "test", "path": "/metadata/resourceVersion", "value": "19"}
        assert [entry["path"] for entry in patch[2:]] == [
            "/spec/rules/0/backendRefs/0/weight",
            "/spec/rules/0/backendRefs/1/weight",
        ]
        assert [entry["value"] for entry in patch[2:]] == [100 - weight, weight]


def test_shadow_route_mirrors_only_read_methods():
    route = gateway.emit_route(
        "apps",
        "route",
        "edge",
        "stable",
        "candidate",
        80,
        0,
        "/slice",
        "ingress",
        "http",
        "app.example",
        True,
    )
    assert route["spec"]["parentRefs"] == [
        {"name": "edge", "namespace": "ingress", "sectionName": "http"}
    ]
    assert route["spec"]["hostnames"] == ["app.example"]
    read, fallback = route["spec"]["rules"]
    assert {match["method"] for match in read["matches"]} == {"GET", "HEAD"}
    assert read["filters"] == [
        {
            "type": "RequestMirror",
            "requestMirror": {"backendRef": {"name": "candidate", "port": 80}},
        }
    ]
    assert all(
        rule["backendRefs"] == [{"name": "stable", "port": 80, "weight": 100}]
        for rule in (read, fallback)
    )
    assert "filters" not in fallback
