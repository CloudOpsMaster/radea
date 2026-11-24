from contextlib import ExitStack
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

from click.testing import CliRunner

from radea.cli import main


def test_parity_compares_json_and_redacts_differences():
    values = [b'{"a":1,"b":2}', b'{"b":2,"a":1}']

    def origin(stack, index):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                assert self.path == "/catalog"
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(values[index])

        server = stack.enter_context(ThreadingHTTPServer(("127.0.0.1", 0), Handler))
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        stack.callback(thread.join)
        stack.callback(server.shutdown)
        return f"http://127.0.0.1:{server.server_port}"

    with ExitStack() as stack:
        arguments = [
            "migration-parity",
            "--legacy",
            origin(stack, 0),
            "--candidate",
            origin(stack, 1),
            "--path",
            "/catalog",
        ]
        runner = CliRunner()
        assert runner.invoke(main, arguments).exit_code == 0
        values[1] = b'{"secret_payload":"private"}'
        mismatch = runner.invoke(main, arguments)
        assert mismatch.exit_code == 2
        assert '"body"' in mismatch.output
        assert "secret_payload" not in mismatch.output
