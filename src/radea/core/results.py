"""Stable result envelope shared by the service and runtime error paths."""

from radea.core.models import Command, Result

SCHEMA_VERSION = "1.0"


def draft_metadata(command: Command, *, evidence_verified: bool = False) -> Result:
    return {
        "schema_version": SCHEMA_VERSION,
        "command": command,
        "draft": True,
        "verified": False,
        "evidence_verified": evidence_verified,
    }


def failure(command: Command, message: str) -> Result:
    return {**draft_metadata(command), "error": message}
