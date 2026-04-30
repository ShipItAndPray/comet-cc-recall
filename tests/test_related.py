from __future__ import annotations

from comet_cc_recall.related import related


def _node(nid, summary="", **kw):
    return {
        "node_id": nid,
        "summary": summary,
        "trigger": kw.get("trigger", ""),
        "topic_tags": kw.get("tags", []),
        "importance": kw.get("importance", "MED"),
        "session_id": kw.get("session_id", "s"),
        "created_at": kw.get("created_at", 1700000000.0),
    }


def test_related_depth_1_returns_hop1(fake_daemon):
    seed = "n_seed"
    children = [_node("c1"), _node("c2")]

    def handler(p):
        assert p["parent_id"] == seed
        return {"ok": True, "nodes": children}

    client, _ = fake_daemon({"list_linked_nodes": handler})
    hits = related(seed, client=client, depth=1)
    assert {h.node_id for h in hits} == {"c1", "c2"}
    # Hop-1 children get score 1.0.
    assert all(h.score == 1.0 for h in hits)


def test_related_depth_2_walks_two_hops(fake_daemon):
    """Each node returned should have its links queried; results merged."""
    graph = {
        "seed": [_node("c1"), _node("c2")],
        "c1": [_node("c3"), _node("seed"), _node("c2")],  # back-edges + dup ignored
        "c2": [_node("c4")],
    }

    def handler(p):
        return {"ok": True, "nodes": graph.get(p["parent_id"], [])}

    client, _ = fake_daemon({"list_linked_nodes": handler})
    hits = related("seed", client=client, depth=2, top_k=20)
    ids = {h.node_id for h in hits}
    assert ids == {"c1", "c2", "c3", "c4"}
    # Hop-1 children outrank hop-2 (decay).
    by_id = {h.node_id: h.score for h in hits}
    assert by_id["c1"] == 1.0
    assert by_id["c3"] < by_id["c1"]


def test_related_excludes_seed(fake_daemon):
    graph = {"seed": [_node("seed"), _node("real")]}
    client, _ = fake_daemon({"list_linked_nodes": lambda p: {"ok": True, "nodes": graph[p["parent_id"]]}})
    hits = related("seed", client=client, depth=1)
    assert [h.node_id for h in hits] == ["real"]


def test_related_top_k_caps(fake_daemon):
    children = [_node(f"c{i}") for i in range(20)]
    client, _ = fake_daemon({"list_linked_nodes": lambda _p: {"ok": True, "nodes": children}})
    hits = related("seed", client=client, depth=1, top_k=5)
    assert len(hits) == 5


def test_related_empty_when_no_links(fake_daemon):
    client, _ = fake_daemon({"list_linked_nodes": lambda _p: {"ok": True, "nodes": []}})
    assert related("seed", client=client) == []
