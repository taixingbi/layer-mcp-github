"""Build / release version (env or default)."""

from __future__ import annotations

import os

SERVICE_NAME = "layer-mcp-github-v1"


def app_version() -> str:
    """Version string from VERSION, BUILD_VERSION, or GIT_SHA env; else ``dev``."""
    for key in ("VERSION", "BUILD_VERSION", "GIT_SHA"):
        value = (os.environ.get(key) or "").strip()
        if value:
            return value
    return "dev"
