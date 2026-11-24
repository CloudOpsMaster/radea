"""Bounded HTTP transport for explicit Prometheus queries."""

import http.client
import json
from typing import Any, Literal
from urllib.parse import urlencode, urlsplit

from radea.static_review.yaml_loader import get


def query(
    endpoint: str, method: Literal["query", "query_range"], params: dict[str, str | float]
) -> Any:
    url = urlsplit(endpoint)
    if (
        url.scheme not in ("http", "https")
        or not url.hostname
        or url.username is not None
        or url.password is not None
        or url.query
        or url.fragment
    ):
        raise ValueError("Provide a plain Prometheus base URL")
    connection_type = (
        http.client.HTTPSConnection if url.scheme == "https" else http.client.HTTPConnection
    )
    port = url.port
    connection = connection_type(url.hostname, port, timeout=10)
    try:
        path = url.path.rstrip("/") + "/api/v1/" + method + "?" + urlencode(params)
        connection.request("GET", path)
        response = connection.getresponse()
        raw = response.read(65537)
        if response.status != 200 or len(raw) > 65536:
            raise ValueError("Prometheus query unavailable")
        data = json.loads(raw)
    except (OSError, http.client.HTTPException, ValueError, RecursionError):
        raise ValueError("Prometheus query unavailable or invalid") from None
    finally:
        connection.close()
    if get(data, "status") != "success" or get(data, "warnings") or get(data, "infos"):
        raise ValueError("Prometheus did not return an unambiguous successful query")
    return get(data, "data")
