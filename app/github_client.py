"""GitHub REST: README and code search."""

from __future__ import annotations

import base64
import os
import re
from typing import Any

import httpx

from app.config import CODE_HITS_MAX, README_MAX, SNIPPET_MAX


def github_token() -> str:
    """Return GitHub PAT from GITHUB_TOKEN or GITHUB_PERSONAL_ACCESS_TOKEN."""
    return (
        os.environ.get("GITHUB_TOKEN") or os.environ.get("GITHUB_PERSONAL_ACCESS_TOKEN") or ""
    ).strip()


def gh_headers() -> dict[str, str]:
    """Default GitHub REST headers including optional Bearer auth."""
    token = github_token()
    h = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def search_keywords(question: str) -> str:
    """Derive a short GitHub code-search query from the user question."""
    words = re.findall(r"[a-zA-Z_][a-zA-Z0-9_]{2,}", question or "")
    if words:
        return " ".join(words[:4])
    cleaned = re.sub(r"[^\w\s-]", " ", question or "")
    parts = [p for p in cleaned.split() if len(p) >= 2][:3]
    return " ".join(parts) if parts else "main"


def fetch_readme(client: httpx.Client, full_name: str) -> str:
    """Fetch and decode the default branch README (truncated to README_MAX)."""
    owner, name = full_name.split("/", 1)
    r = client.get(f"https://api.github.com/repos/{owner}/{name}/readme", headers=gh_headers())
    if r.status_code == 404:
        return ""
    r.raise_for_status()
    data = r.json()
    content = data.get("content") or ""
    encoding = data.get("encoding") or "base64"
    if encoding == "base64" and content:
        raw = base64.b64decode(content).decode("utf-8", errors="replace")
        return raw[:README_MAX]
    return ""


def _search_code(
    client: httpx.Client,
    query: str,
    per_page: int,
) -> list[dict[str, Any]]:
    """Run one GitHub code search; return raw API items (empty on 403/422)."""
    r = client.get(
        "https://api.github.com/search/code",
        params={"q": query, "per_page": per_page},
        headers={**gh_headers(), "Accept": "application/vnd.github.text-match+json"},
    )
    if r.status_code in (403, 422):
        return []
    r.raise_for_status()
    return r.json().get("items") or []


def _item_to_hit(item: dict[str, Any], default_repo: str) -> dict[str, str]:
    """Normalize one search API item to our hit dict."""
    path = item.get("path") or ""
    repo_full = (item.get("repository") or {}).get("full_name") or default_repo
    snippet = ""
    for tm in item.get("text_matches") or []:
        frag = tm.get("fragment") or ""
        if frag:
            snippet = frag.strip()[:SNIPPET_MAX]
            break
    return {
        "path": path,
        "url": item.get("html_url") or "",
        "snippet": snippet,
        "repo": repo_full,
    }


def fetch_code_hits_multi(
    client: httpx.Client,
    full_names: list[str],
    question: str,
    *,
    per_page: int = CODE_HITS_MAX,
) -> list[dict[str, str]]:
    """Code search per repo (multi-repo) or single combined query; dedupe by URL."""
    if not full_names:
        return []
    kw = search_keywords(question)

    if len(full_names) == 1:
        items = _search_code(client, f"{kw} repo:{full_names[0]}", per_page)
    else:
        items = []
        seen_urls: set[str] = set()
        per_repo = max(3, per_page // len(full_names))
        for fn in full_names:
            for item in _search_code(client, f"{kw} repo:{fn}", per_repo):
                url = item.get("html_url") or ""
                if url and url in seen_urls:
                    continue
                if url:
                    seen_urls.add(url)
                items.append(item)
                if len(items) >= per_page:
                    break
            if len(items) >= per_page:
                break

    return [_item_to_hit(item, full_names[0]) for item in items[:per_page]]
