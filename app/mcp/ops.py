"""Operational HTTP endpoints: health, readiness, metrics, version."""

from __future__ import annotations

import os
from typing import Any

import httpx
from prometheus_client import CONTENT_TYPE_LATEST, Info, generate_latest
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.allowlist.repos import ALLOWED_REPOS
from app.clients.github import gh_headers, github_token
from app.clients.llm import llm_api_key, llm_gateway_base, llm_headers
from app.version import SERVICE_NAME, app_version

_READY_TIMEOUT = httpx.Timeout(5.0, connect=3.0)

_INFO = Info("layer_mcp_github", "layer-mcp-github-v1 service metadata")
_INFO.info({"version": app_version(), "service": SERVICE_NAME})


def github_owner() -> str:
    """GitHub org/user from GITHUB_OWNER env."""
    return (os.environ.get("GITHUB_OWNER") or "").strip()


def _config_checks() -> tuple[dict[str, bool], list[str]]:
    checks: dict[str, bool] = {}
    errors: list[str] = []

    checks["github_token"] = bool(github_token())
    if not checks["github_token"]:
        errors.append("GITHUB_TOKEN not set")

    checks["github_owner"] = bool(github_owner())
    if not checks["github_owner"]:
        errors.append("GITHUB_OWNER not set")

    checks["allowlist"] = len(ALLOWED_REPOS) > 0
    if not checks["allowlist"]:
        errors.append("allowlist is empty")

    checks["llm_gateway_config"] = bool(llm_gateway_base())
    if not checks["llm_gateway_config"]:
        errors.append("LLM_GATEWAY_BASE_URL not set")

    return checks, errors


def _probe_github(client: httpx.Client) -> tuple[bool, str | None]:
    if not github_token():
        return False, "GITHUB_TOKEN not set"
    try:
        r = client.get("https://api.github.com/user", headers=gh_headers())
    except httpx.HTTPError as exc:
        return False, f"GitHub API unreachable: {exc}"
    if r.status_code == 401:
        return False, "GitHub token rejected (401)"
    if r.status_code >= 400:
        return False, f"GitHub API error ({r.status_code})"
    return True, None


def _probe_llm_gateway(client: httpx.Client) -> tuple[bool, str | None]:
    base = llm_gateway_base()
    if not base:
        return False, "LLM_GATEWAY_BASE_URL not set"

    headers = llm_headers()
    paths = ("/health", "/v1/models", "")
    last_detail = "LLM gateway unreachable"

    for suffix in paths:
        url = f"{base}{suffix}" if suffix else base
        try:
            r = client.get(url, headers=headers)
        except httpx.HTTPError as exc:
            last_detail = f"LLM gateway unreachable: {exc}"
            continue
        if r.status_code == 401 and llm_api_key() not in ("", "not-needed"):
            return False, "LLM gateway rejected API key (401)"
        if r.status_code < 500:
            return True, None
        last_detail = f"LLM gateway error ({r.status_code})"

    return False, last_detail


def run_readiness_checks() -> dict[str, Any]:
    """Sync dependency probes (GitHub auth + LLM gateway reachability)."""
    checks, errors = _config_checks()

    with httpx.Client(timeout=_READY_TIMEOUT) as client:
        if checks.get("github_token") and checks.get("github_owner"):
            ok, detail = _probe_github(client)
            checks["github_api"] = ok
            if not ok and detail:
                errors.append(detail)
        else:
            checks["github_api"] = False

        if checks.get("llm_gateway_config"):
            ok, detail = _probe_llm_gateway(client)
            checks["llm_gateway"] = ok
            if not ok and detail:
                errors.append(detail)
        else:
            checks["llm_gateway"] = False

    ready = all(checks.values()) and not errors
    return {
        "status": "ready" if ready else "not_ready",
        "service": SERVICE_NAME,
        "version": app_version(),
        "checks": checks,
        "errors": errors,
    }


async def health(_request: Request) -> JSONResponse:
    """Liveness: process is running."""
    return JSONResponse({"status": "ok", "service": SERVICE_NAME})


async def ready(_request: Request) -> JSONResponse:
    """Readiness: config, GitHub auth, and LLM gateway are usable."""
    import anyio

    body = await anyio.to_thread.run_sync(run_readiness_checks)
    status_code = 200 if body["status"] == "ready" else 503
    return JSONResponse(body, status_code=status_code)


async def metrics(_request: Request) -> Response:
    """Prometheus exposition format."""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


async def version(_request: Request) -> JSONResponse:
    """Build / release version."""
    return JSONResponse(
        {
            "service": SERVICE_NAME,
            "version": app_version(),
        }
    )
