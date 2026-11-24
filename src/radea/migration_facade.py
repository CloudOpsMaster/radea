"""Route read-only HTTP requests between two explicitly configured loopback backends."""

import http.client
import re
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, cast

from radea.migration import _path, load_routes, route

MEDIA = re.compile(r"[a-zA-Z0-9!#$&^_.+-]+/[a-zA-Z0-9!#$&^_.+-]+\Z")


class Facade(HTTPServer):
    def __init__(
        self, plan: str, port: int, legacy_port: int, candidate_port: int, limit: int
    ) -> None:
        if not Path(plan).is_file():
            raise ValueError("The migration facade requires a local plan file")
        load_routes(plan, limit)
        if legacy_port == candidate_port:
            raise ValueError("Legacy and candidate need distinct ports")
        self.plan = plan
        self.limit = limit
        self.ports = {"legacy": legacy_port, "candidate": candidate_port}
        super().__init__(("127.0.0.1", port), Handler)
        if self.server_port in self.ports.values():
            self.server_close()
            raise ValueError("The listener cannot also be an upstream")


class Handler(BaseHTTPRequestHandler):
    def setup(self) -> None:
        self.request.settimeout(5)
        super().setup()

    def log_message(self, _format: str, *args: Any) -> None:
        pass

    def _respond(self, status: int, body: bytes, media: str = "text/plain") -> None:
        self.send_response(status)
        self.send_header("Content-Type", media)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if status == 405:
            self.send_header("Allow", "GET, HEAD")
        if self.command != "HEAD" and status != 204:
            self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _forward(self) -> None:
        cohorts = self.headers.get_all("X-RADEA-Cohort", [])
        if (
            len(cohorts) > 1
            or self.headers.get("Transfer-Encoding")
            or any(length != "0" for length in self.headers.get_all("Content-Length", []))
        ):
            self._respond(400, b"Ambiguous cohort or unexpected request body")
            return
        cohort = cohorts[0] if cohorts else ""
        try:
            _path(self.path)
            if cohorts and (not cohort or len(cohort) > 256 or not cohort.isprintable()):
                raise ValueError("Invalid cohort")
        except ValueError:
            self._respond(400, b"Invalid path or cohort")
            return
        server = cast(Facade, self.server)
        try:
            routes = load_routes(server.plan, server.limit)
        except (ValueError, OSError):
            self._respond(503, b"Migration plan unavailable")
            return
        backend = route(routes, self.path, cohort)["backend"] if cohort else "legacy"
        connection = http.client.HTTPConnection("127.0.0.1", server.ports[backend], timeout=5)
        try:
            connection.request(self.command, self.path, headers={"Accept-Encoding": "identity"})
            response = connection.getresponse()
            media = (response.getheader("Content-Type") or "").split(";", 1)[0].strip()
            if not MEDIA.fullmatch(media):
                media = "application/octet-stream"
            encoding = (response.getheader("Content-Encoding") or "identity").lower()
            if (
                not 200 <= response.status <= 599
                or 300 <= response.status < 400
                or encoding != "identity"
            ):
                raise ValueError("Unsupported upstream redirect or encoding")
            body = response.read(min(server.limit, 1_048_576) + 1)
            if len(body) > min(server.limit, 1_048_576):
                raise ValueError("Upstream body exceeds response limit")
        except (OSError, http.client.HTTPException, ValueError):
            self._respond(502, b"Selected upstream unavailable")
            return
        finally:
            connection.close()
        self._respond(response.status, body, media)

    def do_GET(self) -> None:
        self._forward()

    def do_HEAD(self) -> None:
        self._forward()

    def do_POST(self) -> None:
        self._respond(405, b"Only GET and HEAD are supported")
