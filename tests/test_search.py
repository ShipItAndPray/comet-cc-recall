from __future__ import annotations

import pytest

from comet_cc_recall.client import DaemonError
from comet_cc_recall.search import search


def _node(nid, summary="", trigger="", **kw):
    return {
        "node_id": nid,
        "summary": summary,
        "trigger": trigger,
        "topic_tags": kw.get("tags", []),
        "importance": kw.get("importance", "MED"),
        "session_id": kw.get("session_id", "s"),
        "created_at": kw.get("created_at", 1700000000.0),
    }


def test_search_passes_query_to_daemon(fake_daemon):
    captured = {}

    def handler(p):
        captured.update(p)
        return {"ok": True, "nodes": [_node("n1", "ok")]}

    client, _ = fake_daemon({"get_context_window": handler})
    hits = search("redis idempotency race", client=client, top_k=3)
    assert hits[0].node_id == "n1"
    assert captured["query"] == "redis idempotency race"
    assert captured["max_nodes"] >= 3


def test_search_empty_query_returns_empty(fake_daemon):
    client, srv = fake_daemon({"get_context_window": lambda _p: {"ok": True, "nodes": []}})
    assert search("", client=client) == []
    assert search("   ", client=client) == []
    assert not any(m == "get_context_window" for m, _ in srv.calls)


def test_search_dedupes(fake_daemon):
    nodes = [_node("dup"), _node("dup"), _node("other")]
    client, _ = fake_daemon({"get_context_window": lambda _p: {"ok": True, "nodes": nodes}})
    hits = search("q", client=client, top_k=5)
    assert [h.node_id for h in hits] == ["dup", "other"]


def test_search_propagates_daemon_error(fake_daemon):
    client, _ = fake_daemon({"get_context_window": lambda _p: {"ok": False, "error": "boom"}})
    with pytest.raises(DaemonError):
        search("q", client=client)


def test_search_caps_top_k(fake_daemon):
    nodes = [_node(f"n{i}") for i in range(20)]
    client, _ = fake_daemon({"get_context_window": lambda _p: {"ok": True, "nodes": nodes}})
    hits = search("q", client=client, top_k=4)
    assert len(hits) == 4


def test_search_scores_descending(fake_daemon):
    nodes = [_node("a"), _node("b"), _node("c")]
    client, _ = fake_daemon({"get_context_window": lambda _p: {"ok": True, "nodes": nodes}})
    hits = search("q", client=client)
    scores = [h.score for h in hits]
    assert scores == sorted(scores, reverse=True)
