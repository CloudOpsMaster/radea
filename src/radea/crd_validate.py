"""Ask a selected Kubernetes API server to validate a CRD without persisting it."""

import subprocess
from tempfile import TemporaryFile

from radea.core.sanitizer import clean, sanitize
from radea.static_review.files import collect
from radea.static_review.yaml_loader import get, load_all


def validate(source: str, kubeconfig: str, context: str, limit: int) -> dict:
    if not context.strip():
        raise ValueError("Specify a concrete Kubernetes context")
    sources, _ = collect([source], max_bytes=limit)
    if len(sources) != 1:
        raise ValueError("Expected one CRD manifest file")
    manifest = sources[0]
    documents = load_all(manifest.text, strict=True)
    if len(documents) != 1:
        raise ValueError("Expected exactly one CRD document")
    document = documents[0]
    name = get(document, "metadata", "name")
    if (
        get(document, "apiVersion") != "apiextensions.k8s.io/v1"
        or get(document, "kind") != "CustomResourceDefinition"
        or not isinstance(name, str)
        or not name.strip()
    ):
        raise ValueError("Expected a named apiextensions.k8s.io/v1 CustomResourceDefinition")

    diagnostic_limit = min(limit, 8192)
    with TemporaryFile() as stderr:
        try:
            result = subprocess.run(
                [
                    "kubectl", "--kubeconfig", kubeconfig, "--context", context,
                    "--request-timeout=15s", "apply", "--server-side", "--dry-run=server",
                    "--validate=strict", "--field-manager=radea-crd-validation", "-f", "-",
                ],
                input=manifest.text.encode(),
                stdout=subprocess.DEVNULL,
                stderr=stderr,
                timeout=25,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            raise ValueError("kubectl unavailable or validation timed out") from None
        stderr.seek(0)
        diagnostic = stderr.read(diagnostic_limit + 1)
    truncated = len(diagnostic) > diagnostic_limit
    # Drop a partial final line before redaction so a truncated token is never reported.
    if truncated:
        diagnostic = diagnostic[:diagnostic_limit].rpartition(b"\n")[0]
    return clean({
        "schema_version": "1.0",
        "command": "crd-validate",
        "source": manifest.meta(),
        "name": name,
        "accepted": result.returncode == 0,
        "diagnostic": sanitize(diagnostic.decode(errors="replace").strip()).text,
        "diagnostic_truncated": truncated,
    })
