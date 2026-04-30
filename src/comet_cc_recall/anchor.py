"""Build the embedding-query string from (repo, path, symbols).

The order matters: the BGE-M3 embedder weights early tokens slightly more,
so we lead with the most discriminative signal (repo + relative path) and
trail with the symbol list.
"""

from __future__ import annotations

from collections.abc import Iterable


def build_anchor(
    *,
    repo: str | None,
    file_rel: str,
    symbols: Iterable[str],
    language: str | None = None,
) -> str:
    """Compose a single-line anchor query.

    Stable across runs. Empty/None fields are skipped without leaving
    dangling separators.
    """
    parts: list[str] = []
    if repo:
        parts.append(f"repo:{repo}")
    if file_rel:
        parts.append(f"file:{file_rel}")
    if language:
        parts.append(f"lang:{language}")
    sym_list = [s for s in symbols if s]
    if sym_list:
        parts.append("symbols: " + ", ".join(sym_list))
    return " | ".join(parts) if parts else ""
