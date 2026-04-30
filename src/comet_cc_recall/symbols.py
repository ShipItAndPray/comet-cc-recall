"""Best-effort symbol extraction from a source file.

v0 uses regex patterns per language — zero native dependencies, fast,
deterministic, and good enough for ranking purposes (the symbols feed
into a query string, not a parser AST). v0.1 can swap in tree-sitter.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path

# Language → list of (regex, group_idx) pairs that capture top-level
# definition names.
_PATTERNS: dict[str, list[tuple[re.Pattern[str], int]]] = {
    "python": [
        (re.compile(r"^\s*(?:async\s+)?def\s+([A-Za-z_][A-Za-z0-9_]*)", re.M), 1),
        (re.compile(r"^\s*class\s+([A-Za-z_][A-Za-z0-9_]*)", re.M), 1),
    ],
    "typescript": [
        (re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)", re.M), 1),
        (re.compile(r"^\s*(?:export\s+)?class\s+([A-Za-z_$][\w$]*)", re.M), 1),
        (re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=", re.M), 1),
        (re.compile(r"^\s*(?:export\s+)?interface\s+([A-Za-z_$][\w$]*)", re.M), 1),
        (re.compile(r"^\s*(?:export\s+)?type\s+([A-Za-z_$][\w$]*)", re.M), 1),
    ],
    "javascript": [
        (re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)", re.M), 1),
        (re.compile(r"^\s*(?:export\s+)?class\s+([A-Za-z_$][\w$]*)", re.M), 1),
        (re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=", re.M), 1),
    ],
    "go": [
        (re.compile(r"^func\s+(?:\([^)]*\)\s+)?([A-Za-z_][A-Za-z0-9_]*)", re.M), 1),
        (re.compile(r"^type\s+([A-Za-z_][A-Za-z0-9_]*)", re.M), 1),
    ],
    "rust": [
        (re.compile(r"^\s*(?:pub\s+)?fn\s+([A-Za-z_][A-Za-z0-9_]*)", re.M), 1),
        (re.compile(r"^\s*(?:pub\s+)?struct\s+([A-Za-z_][A-Za-z0-9_]*)", re.M), 1),
        (re.compile(r"^\s*(?:pub\s+)?enum\s+([A-Za-z_][A-Za-z0-9_]*)", re.M), 1),
        (re.compile(r"^\s*(?:pub\s+)?trait\s+([A-Za-z_][A-Za-z0-9_]*)", re.M), 1),
    ],
}

_EXT_TO_LANG: dict[str, str] = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".go": "go",
    ".rs": "rust",
}


def detect_language(path: str | Path) -> str | None:
    return _EXT_TO_LANG.get(Path(path).suffix.lower())


def extract_symbols(text: str, language: str, *, top_k: int = 12) -> list[str]:
    """Pull symbol names from `text`. Order is *first appearance* — top-of-
    file definitions usually carry more semantic weight than helpers below.
    De-duplicated, capped at `top_k`."""
    patterns = _PATTERNS.get(language)
    if not patterns:
        return []
    seen: set[str] = set()
    ordered: list[str] = []
    # Walk the file once, all patterns; preserve textual order by using
    # the (pos, name) tuple from finditer.
    candidates: list[tuple[int, str]] = []
    for pat, group_idx in patterns:
        for m in pat.finditer(text):
            name = m.group(group_idx)
            if name and not name.startswith("_"):
                candidates.append((m.start(), name))
    for _, name in sorted(candidates, key=lambda p: p[0]):
        if name in seen:
            continue
        seen.add(name)
        ordered.append(name)
        if len(ordered) >= top_k:
            break
    return ordered


def extract_from_path(path: str | Path, *, top_k: int = 12) -> tuple[str | None, list[str]]:
    """Convenience: read file, detect language, extract symbols.

    Returns `(language, symbols)`. `(None, [])` if file is unreadable or
    the language isn't supported.
    """
    p = Path(path)
    lang = detect_language(p)
    if lang is None:
        return None, []
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return lang, []
    return lang, extract_symbols(text, lang, top_k=top_k)


def join_for_query(symbols: Iterable[str]) -> str:
    """Stable serialization for embedding. Keeps the symbols comma-joined
    so that ordering doesn't fragment the embedding."""
    return ", ".join(symbols)
