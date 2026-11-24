"""Verify detached simple-signing image claims against a trusted public key."""

import base64
import hashlib
import json
import re
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

from radea.gitops import NAMESPACE
from radea.static_review.yaml_loader import get

REPOSITORY = re.compile(r"[a-z0-9][a-z0-9.:-]*(?:/[a-z0-9][a-z0-9._-]*)+\Z")


def _read(path: str, limit: int) -> bytes:
    file = Path(path)
    if not file.is_file():
        raise ValueError("Signature verification inputs must be ordinary files")
    with file.open("rb") as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("Signature verification input exceeds size limit")
    return raw


def _object(pairs: list[tuple]) -> dict:
    result = dict(pairs)
    if len(result) != len(pairs):
        raise ValueError("Duplicate field in image metadata")
    return result


def verify(
    manifest: str, payload: str, signature: str, key: str, repository: str, limit: int
) -> dict:
    if not REPOSITORY.fullmatch(repository):
        raise ValueError("Expected a fully qualified repository without tag or digest")
    raw_manifest = _read(manifest, limit)
    signed = _read(payload, min(limit, 131072))
    public_key = _read(key, 16384).strip().replace(b"\r\n", b"\n")
    if (
        not public_key.startswith(b"-----BEGIN PUBLIC KEY-----\n")
        or not public_key.endswith(b"-----END PUBLIC KEY-----")
        or public_key.count(b"-----BEGIN ") != 1
    ):
        raise ValueError("Expected one trusted PEM public key")
    try:
        metadata = json.loads(raw_manifest, object_pairs_hook=_object)
        claims = json.loads(signed, object_pairs_hook=_object)
        sig = base64.b64decode(_read(signature, 16384).strip(), validate=True)
    except (ValueError, RecursionError):
        raise ValueError("Invalid image manifest, signing payload or base64 signature") from None
    if get(metadata, "schemaVersion") != 2 or not sig:
        raise ValueError("Expected a version-2 image manifest and a nonempty signature")
    digest = "sha256:" + hashlib.sha256(raw_manifest).hexdigest()
    with TemporaryDirectory(prefix="radea-image-") as directory:
        temporary = Path(directory)
        (temporary / "signer.pem").write_bytes(public_key + b"\n")
        (temporary / "signature.bin").write_bytes(sig)
        result = subprocess.run(
            [
                "openssl",
                "dgst",
                "-sha256",
                "-verify",
                str(temporary / "signer.pem"),
                "-signature",
                str(temporary / "signature.bin"),
            ],
            input=signed,
            capture_output=True,
            timeout=10,
            check=False,
        )
    critical = get(claims, "critical")
    if result.returncode != 0:
        reason = "signature_verification_failed"
    elif get(critical, "type") != "cosign container image signature":
        reason = "signature_type_mismatch"
    elif get(critical, "identity", "docker-reference") != repository:
        reason = "repository_mismatch"
    elif get(critical, "image", "docker-manifest-digest") != digest:
        reason = "digest_mismatch"
    else:
        reason = None
    return {
        "schema_version": "1.0",
        "command": "image-verify",
        "verified": reason is None,
        "reason": reason,
        "repository": repository,
        "manifest_digest": digest,
        "public_key_pem_sha256": hashlib.sha256(public_key).hexdigest(),
    }


def admission_config(report: dict, namespace: str) -> dict:
    if report.get("verified") is not True or not NAMESPACE.fullmatch(namespace):
        raise ValueError("Admission config requires a verified image and valid namespace")
    return {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": {"name": "radea-verified-images", "namespace": namespace},
        "data": {"verified": f"{report['repository']}@{report['manifest_digest']}"},
    }
