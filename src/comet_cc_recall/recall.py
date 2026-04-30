"""Main recall orchestrator.

Pipeline:
    file_path
      → extract symbols (regex by language)
      → find repo root + name
      → build anchor string
      → DaemonClient.get_context_window(query=anchor)
      → repo-bonus rerank
      → return RecallHit list

The daemon is the only mandatory external dependency. If it isn't running,
`recall()` raises `DaemonError`; the CLI catches it and prints a hint.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from comet_cc_recall.anchor import build_anchor
from comet_cc_recall.client import DaemonClient, DaemonError
from comet_cc_recall.repo import (
    find_repo_root,
    relative_path,
    repo_match_score,
    repo_name,
)
from comet_cc_recall.symbols import extract_from_path

__all__ = ["RecallHit", "recall", "DaemonError"]

# Constants — tunable, but exposed as parameters where it matters.
DEFAULT_TOP_K = 5
DEFAULT_MIN_SCORE = 0.20
DEFAULT_DAEMON_FETCH = 16  # over-fetch to allow repo rerank to bubble winners


@dataclass(frozen=True)
class RecallHit:
    """One ranked result. `score` is post-rerank (cosine + repo bonus)."""

    node_id: str
    score: float
    summary: str
    trigger: str
    importance: str
    tags: tuple[str, ...]
    session_id: str | None
    created_at: float

    @classmethod
    def from_node_dict(cls, n: dict[str, Any], *, score: float) -> RecallHit:
        tags = n.get("topic_tags") or []
        if isinstance(tags, str):
            tags = [t for t in tags.split(",") if t.strip()]
        return cls(
            node_id=str(n.get("node_id", "")),
            score=float(score),
            summary=str(n.get("summary", "")),
            trigger=str(n.get("trigger", "")),
            importance=str(n.get("importance", "MED")),
            tags=tuple(tags),
            session_id=n.get("session_id"),
            created_at=float(n.get("created_at", 0.0)),
        )


def recall(
    file_path: str | Path,
    *,
    client: DaemonClient | None = None,
    top_k: int = DEFAULT_TOP_K,
    min_score: float = DEFAULT_MIN_SCORE,
    fetch: int = DEFAULT_DAEMON_FETCH,
    repo_filter: bool = True,
    session_id: str = "comet-cc-recall-probe",
) -> list[RecallHit]:
    """Recall memory nodes anchored to `file_path`.

    Parameters
    ----------
    file_path : str | Path
        Source file the user just opened or referenced.
    client : DaemonClient, optional
        Defaults to `DaemonClient.default()`. Tests pass a fake.
    top_k : int
        Final result count after rerank.
    min_score : float
        Cosine floor passed to the daemon. Daemon may apply its own floor.
    fetch : int
        How many candidates to over-fetch from the daemon for rerank.
    repo_filter : bool
        When True, apply the repo-match additive bonus.
    session_id : str
        Probe session id, used solely so the daemon's `get_context_window`
        accepts the call. Cross-session results require the daemon to
        have been started with `COMET_CC_CROSS_SESSION=1`.

    Returns
    -------
    list[RecallHit]
        Ranked, deduped, length ≤ top_k.
    """
    p = Path(file_path)
    cli = client or DaemonClient.default()

    repo_root = find_repo_root(p)
    name = repo_name(repo_root, fallback=p)
    rel = relative_path(p, repo_root)
    lang, symbols = extract_from_path(p)

    # Unsupported file types yield no useful semantic signal — skip the
    # daemon round-trip rather than embedding a bare filename.
    if lang is None and not symbols:
        return []

    anchor = build_anchor(repo=name, file_rel=rel, symbols=symbols, language=lang)
    if not anchor:
        return []

    nodes = cli.get_context_window(
        session_id=session_id,
        query=anchor,
        max_nodes=max(top_k, fetch),
        min_score=min_score,
    )

    # Deduplicate (the daemon already returns unique parents, but defend).
    seen: set[str] = set()
    raw: list[dict[str, Any]] = []
    for n in nodes:
        nid = n.get("node_id")
        if not nid or nid in seen:
            continue
        seen.add(nid)
        raw.append(n)

    # Rerank: the existing RPC doesn't return per-node cosine scores, so we
    # synthesize a tight positional decay (1.0, 0.99, 0.98, …) preserving
    # the daemon's own ordering as a tie-break, and add the repo bonus on
    # top. The bonus dominates intentionally — that's the whole point of
    # file-anchored recall.
    hits: list[RecallHit] = []
    for idx, n in enumerate(raw):
        positional = 1.0 - 0.01 * idx
        bonus = 0.0
        if repo_filter:
            text = " ".join((n.get("summary") or "", n.get("trigger") or ""))
            bonus = repo_match_score(text, repo=name, file_rel=rel)
        hits.append(RecallHit.from_node_dict(n, score=positional + bonus))

    hits.sort(key=lambda h: h.score, reverse=True)
    return hits[:top_k]
