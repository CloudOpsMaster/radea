"""RADEA — Reliable AI-Driven Engineering Automation."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("radea")
except PackageNotFoundError:
    __version__ = "0+unknown"
