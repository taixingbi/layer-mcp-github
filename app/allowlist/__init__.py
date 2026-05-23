"""Allowlisted GitHub repo resolution."""

from app.allowlist.repos import ALLOWED_REPOS
from app.allowlist.resolve import (
    allowed_short_names,
    fail,
    resolve_repo,
    resolve_repos,
)

__all__ = [
    "ALLOWED_REPOS",
    "allowed_short_names",
    "fail",
    "resolve_repo",
    "resolve_repos",
]
