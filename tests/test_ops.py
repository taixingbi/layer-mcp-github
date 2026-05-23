"""CI smoke tests (no GitHub / LLM network)."""

import tomllib
from pathlib import Path

from starlette.testclient import TestClient

from app.mcp.app import create_mcp_app
from app.version import app_version


def _pyproject_version() -> str:
    data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    return str(data["project"]["version"])


def test_app_version_matches_pyproject() -> None:
    assert app_version() == _pyproject_version()


def test_health_and_version_endpoints() -> None:
    client = TestClient(create_mcp_app())
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"

    version = client.get("/version")
    assert version.status_code == 200
    body = version.json()
    assert body["version"] == app_version()
    assert body["service"] == "layer-mcp-github-v1"
