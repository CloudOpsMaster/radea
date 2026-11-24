"""Compare bounded read-only responses before moving a migration slice."""

import http.client
import json
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit

from radea.migration import _path


def _read(base: str, path: str, limit: int) -> tuple[int, str, bytes]:
    url = urlsplit(base)
    if (
        url.scheme not in ("http", "https")
        or not url.hostname
        or url.username is not None
        or url.password is not None
        or url.query
        or url.fragment
        or url.path not in ("", "/")
    ):
        raise ValueError("Expected an HTTP(S) origin without credentials")
    connection_type = (
        http.client.HTTPSConnection if url.scheme == "https" else http.client.HTTPConnection
    )
    connection = connection_type(url.hostname, url.port, timeout=5)
    try:
        connection.request("GET", path, headers={"Accept-Encoding": "identity"})
        response = connection.getresponse()
        body = response.read(limit + 1)
        if len(body) > limit:
            raise ValueError("Migration response exceeded the byte limit")
        media = response.headers.get_content_type()
        return response.status, media, body
    except (OSError, http.client.HTTPException):
        raise ValueError("Migration probe failed to read a backend response") from None
    finally:
        connection.close()


def _canonical_json(body: bytes) -> str:
    try:
        return json.dumps(json.loads(body), sort_keys=True, allow_nan=False)
    except (ValueError, RecursionError):
        raise ValueError("Invalid JSON in migration response") from None


def compare(legacy: str, candidate: str, path: str, limit: int) -> dict:
    path = _path(path)
    with ThreadPoolExecutor(max_workers=2) as executor:
        legacy_request = executor.submit(_read, legacy, path, limit)
        candidate_request = executor.submit(_read, candidate, path, limit)
        stable_status, stable_media, stable_body = legacy_request.result()
        candidate_status, candidate_media, candidate_body = candidate_request.result()

    body_matches = stable_body == candidate_body
    if stable_media == candidate_media == "application/json":
        body_matches = _canonical_json(stable_body) == _canonical_json(candidate_body)
    differences = []
    if stable_status != candidate_status:
        differences.append("status")
    if stable_media != candidate_media:
        differences.append("content_type")
    if not body_matches:
        differences.append("body")
    if not 200 <= stable_status < 300 or not 200 <= candidate_status < 300:
        differences.append("unsuccessful_response")
    return {
        "schema_version": "1.0",
        "command": "migration-parity",
        "legacy_status": stable_status,
        "candidate_status": candidate_status,
        "matches": not differences,
        "differences": differences,
    }
