"""Graph-walk recall — `comet-cc-recall related <node_id>`.

Returns the similarity-linked peers of a given node, ranked by tier
(direct hop1 first, then `links` of those if `--depth 2`). De-duplicates
and excludes the seed node.
"""

from __future__ import annotations

from typing import Any

from comet_cc_recall.client import DaemonClient
from comet_cc_recall.recall import RecallHit


def related(
    node_id: str,
    *,
    client: DaemonClient | None = None,
    depth: int = 1,
    top_k: int = 8,
) -> list[RecallHit]:
    """Walk the node graph from `node_id`.

    depth=1 → list_linked_nodes(node_id)
    depth=2 → also pull each hop-1 child's links and dedup

    Returns hits with descending scores: hop-1 children at score 1.0,
    hop-2 children at 0.6 (decay).
    """
    cli = client or DaemonClient.default()

    seen: set[str] = {node_id}
    by_id: dict[str, dict[str, Any]] = {}
    score_for: dict[str, float] = {}

    hop1 = cli.list_linked_nodes(node_id)
    for n in hop1:
        nid = n.get("node_id")
        if not nid or nid in seen:
            continue
        seen.add(nid)
        by_id[nid] = n
        score_for[nid] = 1.0

    if depth >= 2:
        for parent in list(hop1):
            pid = parent.get("node_id")
            if not pid:
                continue
            try:
                hop2 = cli.list_linked_nodes(pid)
            except Exception:  # pragma: no cover - defensive
                continue
            for n in hop2:
                nid = n.get("node_id")
                if not nid or nid in seen:
                    continue
                seen.add(nid)
                by_id[nid] = n
                score_for[nid] = 0.6

    hits: list[RecallHit] = []
    for nid, node in by_id.items():
        hits.append(RecallHit.from_node_dict(node, score=score_for[nid]))
    hits.sort(key=lambda h: (-h.score, h.created_at), reverse=False)
    # Sort key above: highest score first, ties broken by older first; we
    # invert by reversing the score sign — but tie-break ordering should
    # actually be newer first (more recent context wins). Re-sort cleanly:
    hits.sort(key=lambda h: (h.score, h.created_at), reverse=True)
    return hits[:top_k]
