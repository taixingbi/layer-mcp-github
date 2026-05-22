"""Citation numbering and LLM source formatting."""

from __future__ import annotations

from typing import Any

from app.config import LLM_CONTEXT_README_MAX, MULTI_REPO_README_MAX


def repo_web_url(full_name: str) -> str:
    return f"https://github.com/{full_name}"


def build_citations(
    full_name: str,
    readme: str,
    code_hits: list[dict[str, str]],
    *,
    readme_label: str | None = None,
) -> list[dict[str, Any]]:
    citations: list[dict[str, Any]] = []
    idx = 1
    if readme:
        label = readme_label or "README"
        citations.append(
            {
                "index": idx,
                "url": repo_web_url(full_name),
                "label": label,
                "repo": full_name,
                "type": "repository",
            }
        )
        idx += 1
    seen_urls: set[str] = set()
    for hit in code_hits:
        repo = hit.get("repo") or full_name
        path = hit.get("path") or ""
        url = (hit.get("url") or "").strip()
        if not url and path:
            url = f"https://github.com/{repo}/blob/HEAD/{path}"
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        short = repo.split("/", 1)[-1] if "/" in repo else repo
        label = f"{short}/{path}" if path else path or url
        citations.append(
            {
                "index": idx,
                "url": url,
                "label": label,
                "repo": repo,
                "type": "code",
            }
        )
        idx += 1
    if not citations:
        citations.append(
            {
                "index": 1,
                "url": repo_web_url(full_name),
                "label": full_name,
                "repo": full_name,
                "type": "repository",
            }
        )
    return citations


def merge_citations(repo_blocks: list[tuple[str, list[dict[str, Any]]]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    offset = 0
    for _full_name, block in repo_blocks:
        for c in block:
            merged.append({**c, "index": offset + int(c["index"])})
        offset = len(merged)
    return merged


def format_sources_for_llm(
    citations: list[dict[str, Any]], readme: str, code_hits: list[dict[str, str]]
) -> str:
    lines = ["## Sources (use [n] in answer)"]
    for c in citations:
        lines.append(f"[{c['index']}] {c.get('label', '')} — {c['url']}")
    if readme:
        lines.append(f"\n## README excerpt\n{readme[:LLM_CONTEXT_README_MAX]}")
    if code_hits:
        lines.append("\n## Code snippets")
        for hit in code_hits:
            repo = hit.get("repo") or ""
            prefix = f"{repo}/" if repo else ""
            lines.append(f"### {prefix}{hit.get('path', '')}\n{hit.get('snippet') or '(no snippet)'}")
    return "\n".join(lines)


def format_multi_repo_sources(
    citations: list[dict[str, Any]],
    readmes: dict[str, str],
    code_hits: list[dict[str, str]],
) -> str:
    lines = ["## Sources (use [n] in answer)"]
    for c in citations:
        lines.append(f"[{c['index']}] {c.get('label', '')} — {c['url']}")
    if readmes:
        lines.append("\n## README excerpts")
        for full_name, text in readmes.items():
            if text:
                lines.append(f"\n### {full_name}\n{text[:MULTI_REPO_README_MAX]}")
    if code_hits:
        lines.append("\n## Code snippets")
        for hit in code_hits:
            repo = hit.get("repo") or ""
            lines.append(f"### {repo}/{hit.get('path', '')}\n{hit.get('snippet') or '(no snippet)'}")
    return "\n".join(lines)
