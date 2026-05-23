"""Build / release version from pyproject.toml (installed package metadata)."""

from __future__ import annotations

SERVICE_NAME = "layer-mcp-github-v1"
_DIST_NAME = "layer-mcp-github-v1"


def app_version() -> str:
    """Version from installed package metadata ([project].version in pyproject.toml)."""
    try:
        from importlib.metadata import version

        return version(_DIST_NAME)
    except Exception:
        return "dev"
