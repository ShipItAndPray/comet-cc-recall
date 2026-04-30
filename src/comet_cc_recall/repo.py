"""Locate the repo root + name for a given path.

Used to (a) anchor the embedding query and (b) filter recalled nodes to
ones that mention the same repo. Falls back gracefully when the file
isn't inside a git repo (e.g., scratch dirs).
"""

from __future__ import annotations

from pathlib import Path


def find_repo_root(path: str | Path) -> Path | None:
    """Walk up looking for `.git`. Returns the directory containing it, or
    `None` if not found before the filesystem root."""
    p = Path(path).resolve()
    if p.is_file():
        p = p.parent
    for candidate in (p, *p.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def repo_name(repo_root: Path | None, fallback: str | Path | None = None) -> str | None:
    if repo_root is not None:
        return repo_root.name or None
    if fallback is not None:
        return Path(fallback).resolve().parent.name or None
    return None


def relative_path(path: str | Path, repo_root: Path | None) -> str:
    """Path string, repo-relative if possible — else absolute basename."""
    p = Path(path).resolve()
    if repo_root is not None:
        try:
            return str(p.relative_to(repo_root))
        except ValueError:
            pass
    return p.name


def repo_match_score(node_text: str, *, repo: str | None, file_rel: str) -> float:
    """Boost a node when its summary/trigger/raw mentions the same file or
    repo. Bounded [0.0, 1.0] additive bonus, applied after the cosine score.

    Heuristic — we don't have raw turns at this layer so we rely on what
    the daemon returns in the node dict (summary + trigger). File path
    match is heavier than repo-name match because file is more specific.
    """
    if not node_text:
        return 0.0
    text = node_text.lower()
    score = 0.0
    if file_rel:
        # Try the full relative path, then the basename.
        rel_lower = file_rel.lower()
        if rel_lower in text:
            score += 0.25
        else:
            base = Path(file_rel).name.lower()
            if base and base in text:
                score += 0.15
    if repo and repo.lower() in text:
        score += 0.05
    return min(score, 0.4)
