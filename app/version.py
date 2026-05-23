"""Build / release version (pyproject.toml, env override, or default)."""

from __future__ import annotations

import os

SERVICE_NAME = "layer-mcp-github-v1"
_DIST_NAME = "layer-mcp-github-v1"


def _package_version() -> str | None:
    try:
        from importlib.metadata import version

        return version(_DIST_NAME)
    except Exception:
        return None


def app_version() -> str:
    """Version from VERSION/BUILD_VERSION/GIT_SHA env, else installed package metadata, else ``dev``."""
    for key in ("VERSION", "BUILD_VERSION", "GIT_SHA"):
        value = (os.environ.get(key) or "").strip()
        if value:
            return value
    return _package_version() or "dev"
