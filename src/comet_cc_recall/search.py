"""Raw semantic search — `comet-cc-recall search "<query>"`.

Bypasses the file anchor entirely. Useful when you don't have a file
open or when you want to recall by natural-language description rather
than by code surface.
"""

from __future__ import annotations

from typing import Any

from comet_cc_recall.client import DaemonClient
from comet_cc_recall.recall import (
    DEFAULT_DAEMON_FETCH,
    DEFAULT_MIN_SCORE,
    DEFAULT_TOP_K,
    RecallHit,
)


def search(
    query: str,
    *,
    client: DaemonClient | None = None,
    top_k: int = DEFAULT_TOP_K,
    min_score: float = DEFAULT_MIN_SCORE,
    fetch: int = DEFAULT_DAEMON_FETCH,
    session_id: str = "comet-cc-recall-search",
) -> list[RecallHit]:
    """Return the top-K nodes by cosine similarity to `query`."""
    if not query or not query.strip():
        return []
    cli = client or DaemonClient.default()
    nodes = cli.get_context_window(
        session_id=session_id,
        query=query,
        max_nodes=max(top_k, fetch),
        min_score=min_score,
    )
    seen: set[str] = set()
    raw: list[dict[str, Any]] = []
    for n in nodes:
        nid = n.get("node_id")
        if not nid or nid in seen:
            continue
        seen.add(nid)
        raw.append(n)

    hits: list[RecallHit] = []
    for idx, n in enumerate(raw):
        positional = 1.0 - 0.01 * idx
        hits.append(RecallHit.from_node_dict(n, score=positional))
    return hits[:top_k]
