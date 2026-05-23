"""Allowlisted repo resolution."""

from __future__ import annotations

import os
from typing import Any

from app.allowlist.repos import ALLOWED_REPOS


def allowed_short_names() -> list[str]:
    """Return allowlisted repo short names (no owner prefix)."""
    return list(ALLOWED_REPOS)


def fail(error: str, repo: str = "", **extra: Any) -> dict[str, Any]:
    """Standard error payload including allowed repo list."""
    out: dict[str, Any] = {"ok": False, "error": error, "allowed": allowed_short_names()}
    if repo:
        out["repo"] = repo
    out.update(extra)
    return out


def _github_owner() -> str:
    """GitHub org/user from GITHUB_OWNER env."""
    return (os.environ.get("GITHUB_OWNER") or "").strip()


def _resolve_single_repo(raw: str, allowed: list[str], owner: str) -> dict[str, Any]:
    """Validate one repo string against owner + allowlist."""
    if "/" in raw:
        parts = raw.split("/", 1)
        if len(parts) != 2 or not parts[0] or not parts[1]:
            return fail("invalid owner/name format", repo=raw)
        repo_owner, short = parts[0], parts[1]
        if repo_owner != owner:
            return fail(f"owner must be {owner} (got {repo_owner})", repo=raw)
        if short not in allowed:
            return fail("repo not allowed", repo=raw)
        return {"ok": True, "full_name": f"{owner}/{short}", "short": short}

    if raw not in allowed:
        return fail("repo not allowed", repo=raw)
    return {"ok": True, "full_name": f"{owner}/{raw}", "short": raw}


def resolve_repo(repo: str) -> dict[str, Any]:
    """Validate one repo against allowlist; return ``{ok, full_name}`` or error dict."""
    allowed = allowed_short_names()
    if not allowed:
        return fail("allowlist is empty")

    owner = _github_owner()
    if not owner:
        return fail("GITHUB_OWNER not set in .env")

    raw = (repo or "").strip()
    if not raw:
        return fail("repo is required", repo=raw)

    return _resolve_single_repo(raw, allowed, owner)


def resolve_repos(repo: str | None = None) -> dict[str, Any]:
    """Resolve one repo or all allowlisted repos when ``repo`` is omitted."""
    allowed = allowed_short_names()
    if not allowed:
        return fail("allowlist is empty")

    owner = _github_owner()
    if not owner:
        return fail("GITHUB_OWNER not set in .env")

    raw = (repo or "").strip()
    if not raw:
        return {
            "ok": True,
            "full_names": [f"{owner}/{short}" for short in allowed],
            "shorts": allowed,
            "scope": "all",
        }

    one = resolve_repo(raw)
    if not one.get("ok"):
        return one
    return {
        "ok": True,
        "full_names": [one["full_name"]],
        "shorts": [one["short"]],
        "scope": one["full_name"],
    }
