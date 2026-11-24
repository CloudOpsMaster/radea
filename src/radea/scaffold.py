"""Generate a deterministic service starter in a new local directory."""

import re
import shutil
from importlib.resources import files
from pathlib import Path

import yaml

NAME = re.compile(r"[a-z][a-z0-9-]{0,62}\Z")
BASE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]*@sha256:[a-f0-9]{64}\Z")
TEMPLATES = {
    "app.py": "app.py.tmpl",
    "test_app.py": "test_app.py.tmpl",
    "Dockerfile": "Dockerfile.tmpl",
    ".github/workflows/ci.yml": "ci.yml.tmpl",
    "README.md": "README.md.tmpl",
}


def scaffold(
    name: str, base_image: str, destination: Path, *, owner: str | None = None,
) -> list[str]:
    if not NAME.fullmatch(name) or name.endswith("-"):
        raise ValueError("Service name must be a lowercase DNS label")
    if not BASE.fullmatch(base_image):
        raise ValueError("Base image must be an image reference pinned by SHA-256")
    if owner is not None and (not NAME.fullmatch(owner) or owner.endswith("-")):
        raise ValueError("Catalog owner must be a lowercase group name")
    template_dir = files("radea").joinpath("data").joinpath("golden")
    contents = {
        target: template_dir.joinpath(template)
        .read_text(encoding="utf-8")
        .replace("{{NAME}}", name)
        .replace("{{BASE_IMAGE}}", base_image)
        for target, template in TEMPLATES.items()
    }
    if owner is not None:
        contents["catalog-info.yaml"] = yaml.safe_dump({
            "apiVersion": "backstage.io/v1alpha1",
            "kind": "Component",
            "metadata": {"name": name},
            "spec": {"type": "service", "lifecycle": "experimental", "owner": owner},
        }, sort_keys=False)
    destination.mkdir()
    try:
        for target, content in contents.items():
            path = destination / target
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("x", encoding="utf-8") as stream:
                stream.write(content)
    except OSError:
        shutil.rmtree(destination, ignore_errors=True)
        raise
    return list(contents)
