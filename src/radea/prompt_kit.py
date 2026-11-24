"""Build a versioned prompt packet from a local team library and structured context."""

import json
import re

from radea.core.sanitizer import clean
from radea.static_review.files import collect

NAME = re.compile(r"[a-z][a-z0-9_-]{0,63}\Z")


def _read(path: str, limit: int) -> tuple[dict, dict]:
    files, _ = collect([path], max_bytes=limit)
    if len(files) != 1:
        raise ValueError("Expected a single JSON file per input")
    try:
        parsed = json.loads(files[0].text)
    except (ValueError, RecursionError):
        raise ValueError("Invalid prompt library or context JSON") from None
    if not isinstance(parsed, dict):
        raise ValueError("Prompt inputs must be JSON objects")
    return parsed, files[0].meta()


def prepare(library: str, context: str, template_id: str, version: str, limit: int) -> dict:
    if library == context == "-":
        raise ValueError("Only one prompt input may use stdin")
    if not NAME.fullmatch(template_id) or not re.fullmatch(r"[0-9]+(?:\.[0-9]+){0,2}", version):
        raise ValueError("Expected a lowercase template ID and numeric version")
    config, source = _read(library, limit)
    values, context_source = _read(context, limit)
    templates = config.get("templates")
    if not isinstance(templates, list) or not 1 <= len(templates) <= 200:
        raise ValueError("Prompt library requires 1–200 templates")
    if not all(isinstance(item, dict) for item in templates):
        raise ValueError("Every prompt template must be a JSON object")
    matches = [
        item
        for item in templates
        if item.get("id") == template_id and item.get("version") == version
    ]
    if len(matches) != 1:
        raise ValueError("Expected exactly one template with that ID and version")
    template = matches[0]
    instruction, fields = template.get("instruction"), template.get("inputs")
    if not isinstance(instruction, str) or not instruction.strip() or len(instruction) > 12000:
        raise ValueError("Expected a nonempty instruction of at most 12000 characters")
    if (
        not isinstance(fields, list)
        or len(fields) > 30
        or not all(isinstance(key, str) and NAME.fullmatch(key) for key in fields)
        or len(set(fields)) != len(fields)
    ):
        raise ValueError("Template inputs must be distinct lowercase labels")
    if set(values) != set(fields) or not all(
        isinstance(value, str) and len(value) <= 8000 for value in values.values()
    ):
        raise ValueError("Context must match the declared fields and use bounded strings")
    return clean(
        {
            "schema_version": "1.0",
            "command": "prompt-prepare",
            "draft": True,
            "template": {"id": template_id, "version": version, "sha256": source["sha256"]},
            "context_sha256": context_source["sha256"],
            "instruction": instruction.strip(),
            "untrusted_context": values,
        }
    )
