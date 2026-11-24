import json
from urllib.parse import parse_qs, urlsplit

import pytest
from click.testing import CliRunner

from radea.cli import main


@pytest.mark.parametrize("invalid", [None, "gap", "nonfinite", "ambiguous"])
def test_metric_anomalies_reads_prometheus_range(monkeypatch, tmp_path, invalid):
    endpoint = "http://127.0.0.1:9090/prometheus"
    source = tmp_path / "queries.json"
    source.write_text(json.dumps({"queries": {"errors": "sum(errors_total)"}}))
    monkeypatch.setattr("time.time", lambda: 123)
    samples = [[timestamp, "10"] for timestamp in range(70, 120, 10)] + [[120, "30"]]
    if invalid == "gap":
        samples[2][0] = 91
    if invalid == "nonfinite":
        samples[-1][1] = "NaN"
    rows = [{"values": samples}]
    if invalid == "ambiguous":
        rows *= 2

    class Connection:
        status = 200

        def __init__(self, host, port, timeout):
            assert (host, port, timeout) == ("127.0.0.1", 9090, 10)

        def request(self, method, path):
            url = urlsplit(path)
            assert (method, url.path) == ("GET", "/prometheus/api/v1/query_range")
            assert parse_qs(url.query) == {
                "query": ["sum(errors_total)"], "start": ["70.0"], "end": ["120.0"],
                "step": ["10s"], "timeout": ["5s"],
            }

        def getresponse(self):
            return self

        def read(self, size):
            assert size == 65537
            return json.dumps({
                "status": "success", "data": {"resultType": "matrix", "result": rows},
            }).encode()

        def close(self):
            pass

    monkeypatch.setattr("radea.prometheus.http.client.HTTPConnection", Connection)
    result = CliRunner().invoke(main, [
        "metric-anomalies", str(source), "--prometheus", endpoint, "--window", "5",
        "--step", "10", "--fail-on-anomaly",
    ])
    if invalid:
        assert result.exit_code == 1, result.output
        assert "Prometheus" in result.output
    else:
        assert result.exit_code == 2, result.output
        report = json.loads(result.output)
        assert report["sampled_at"] == 120
        assert report["metrics"][0]["delta"] == 20
