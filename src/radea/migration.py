"""Plan a deterministic routing decision for an incremental service migration."""

import hashlib
import json
import re

from radea.static_review.files import collect

SEGMENTS = re.compile(r"/(?:[A-Za-z0-9._~-]+(?:/[A-Za-z0-9._~-]+)*/?)?\Z")


def _path(value) -> str:
    if (
        not isinstance(value, str)
        or len(value) > 2048
        or not SEGMENTS.fullmatch(value)
        or any(segment in {".", ".."} for segment in value.split("/"))
    ):
        raise ValueError("Expected a normalized path without query, encoding or dot segments")
    return value.rstrip("/") or "/"


def cohort_bucket(scope: str, cohort: str) -> int:
    if not cohort or len(cohort) > 256 or "\0" in cohort:
        raise ValueError("Expected a nonempty stable cohort ID of up to 256 characters")
    digest = hashlib.sha256(f"{scope}\0{cohort}".encode()).digest()
    return int.from_bytes(digest[:8], "big") * 100 // 2**64


def load_routes(plan: str, limit: int) -> dict[str, int]:
    sources, _ = collect([plan], max_bytes=limit)
    if len(sources) != 1:
        raise ValueError("Expected one migration route plan")
    try:
        document = json.loads(sources[0].text)
    except (ValueError, RecursionError):
        raise ValueError("Invalid migration plan JSON") from None
    records = document.get("routes") if isinstance(document, dict) else None
    if not isinstance(records, list) or len(records) > 500:
        raise ValueError("Expected a routes list of up to 500 entries")
    routes: dict[str, int] = {}
    for route in records:
        if not isinstance(route, dict):
            raise ValueError("Each migration route must be an object")
        prefix = _path(route.get("prefix"))
        percentage = route.get("candidate_percent")
        if type(percentage) is not int or not 0 <= percentage <= 100:
            raise ValueError("candidate_percent must be an integer between 0 and 100")
        if prefix in routes:
            raise ValueError("Duplicate migration route prefix")
        routes[prefix] = percentage
    return routes


def route(routes: dict[str, int], path: str, cohort: str) -> dict:
    requested = _path(path)
    matching = [
        prefix
        for prefix in routes
        if prefix == "/" or requested == prefix or requested.startswith(prefix + "/")
    ]
    selected = max(matching, key=len) if matching else None
    weight = routes[selected] if selected is not None else 0
    bucket = cohort_bucket(selected or "/", cohort)
    return {
        "schema_version": "1.0",
        "command": "migration-route",
        "matched_prefix": selected,
        "candidate_percent": weight,
        "backend": "candidate" if bucket < weight else "legacy",
    }


def decide(plan: str, path: str, cohort: str, limit: int) -> dict:
    return route(load_routes(plan, limit), path, cohort)
