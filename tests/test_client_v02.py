"""Client-level coverage for the new RPC wrappers."""

from __future__ import annotations

import pytest

from comet_cc_recall.client import DaemonError


def test_get_node_returns_node_dict(fake_daemon):
    payload = {"ok": True, "node": {"node_id": "n", "summary": "s"}}
    client, srv = fake_daemon({"get_node": lambda _p: payload})
    out = client.get_node("n")
    assert out["summary"] == "s"
    method, params = srv.calls[-1]
    assert method == "get_node"
    assert params["node_id"] == "n"


def test_get_node_error(fake_daemon):
    client, _ = fake_daemon({"get_node": lambda _p: {"ok": False, "error": "x"}})
    with pytest.raises(DaemonError, match="x"):
        client.get_node("n")


def test_get_node_missing_node_field(fake_daemon):
    client, _ = fake_daemon({"get_node": lambda _p: {"ok": True}})
    with pytest.raises(DaemonError, match="no node"):
        client.get_node("n")


def test_list_linked_nodes(fake_daemon):
    nodes = [{"node_id": "c1"}, {"node_id": "c2"}]
    client, srv = fake_daemon({"list_linked_nodes": lambda _p: {"ok": True, "nodes": nodes}})
    out = client.list_linked_nodes("p")
    assert [n["node_id"] for n in out] == ["c1", "c2"]
    method, params = srv.calls[-1]
    assert method == "list_linked_nodes"
    assert params["parent_id"] == "p"


def test_list_linked_nodes_error(fake_daemon):
    client, _ = fake_daemon({"list_linked_nodes": lambda _p: {"ok": False, "error": "boom"}})
    with pytest.raises(DaemonError):
        client.list_linked_nodes("p")
