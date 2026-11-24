import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

from click.testing import CliRunner

from radea.cli import main


def test_smoke_gates_expected_responses_and_keeps_bodies_private(monkeypatch, tmp_path):
    kubeconfig = tmp_path / "kubeconfig"
    kubeconfig.touch()
    paths = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            paths.append(self.path)
            healthy = self.path == "/health/"
            self.send_response(200 if healthy else 503)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}' if healthy else b'{"private_field":"value"}')

    def rollout(base, arguments, limit):
        assert base == [
            "kubectl", "--kubeconfig", str(kubeconfig), "--context", "lab",
            "--namespace", "test", "--request-timeout=15s",
        ]
        assert arguments == ["rollout", "status", "deployment/app", "--timeout=12s"]
        return b"ready"

    monkeypatch.setattr("radea.kube_smoke._get", rollout)
    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        args = [
            "k8s-smoke", "-", "--origin", f"http://127.0.0.1:{server.server_port}",
            "--kubeconfig", str(kubeconfig), "--context", "lab",
            "--namespace", "test", "--deployment", "app",
        ]
        cases = [{"path": "/health/", "status": 200, "json": {"status": "ok"}},
                 {"path": "/degraded", "status": 503}]
        runner = CliRunner()
        try:
            assert runner.invoke(main, args, input=json.dumps(cases)).exit_code == 0
            cases[1].update(status=200, json={"status": "ok"})
            result = runner.invoke(main, args, input=json.dumps(cases))
            assert result.exit_code == 2, result.output
            assert json.loads(result.output)["cases"][1]["differences"] == ["status", "json"]
            assert "private_field" not in result.output
            assert paths == ["/health/", "/degraded"] * 2

            def unavailable(*args):
                raise ValueError("simulated rollout failure")

            monkeypatch.setattr("radea.kube_smoke._get", unavailable)
            result = runner.invoke(main, args, input=json.dumps(cases))
            assert result.exit_code == 1
            assert "readiness" in result.output
            assert len(paths) == 4
        finally:
            server.shutdown()
            thread.join()
