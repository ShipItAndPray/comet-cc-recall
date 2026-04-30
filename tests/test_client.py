from __future__ import annotations

import time

import pytest

from comet_cc_recall.client import DaemonClient, DaemonError


def test_ping_succeeds(fake_daemon):
    client, srv = fake_daemon({"ping": lambda _p: {"ok": True, "ts": time.time()}})
    assert client.is_running() is True
    assert any(m == "ping" for m, _ in srv.calls)


def test_ping_when_socket_missing(tmp_path):
    client = DaemonClient(tmp_path / "nope.sock")
    assert client.is_running() is False


def test_get_context_window_returns_nodes(fake_daemon):
    nodes = [
        {
            "node_id": "n_aaa",
            "summary": "redis SETNX race",
            "trigger": "idempotency key collisions",
            "topic_tags": ["payments", "redis"],
            "importance": "HIGH",
            "session_id": "s1",
            "created_at": 1700000000.0,
        }
    ]
    client, _ = fake_daemon({"get_context_window": lambda _p: {"ok": True, "nodes": nodes}})
    out = client.get_context_window(session_id="probe", query="x", max_nodes=5, min_score=0.2)
    assert out == nodes


def test_get_context_window_raises_on_error(fake_daemon):
    client, _ = fake_daemon(
        {"get_context_window": lambda _p: {"ok": False, "error": "boom"}}
    )
    with pytest.raises(DaemonError, match="boom"):
        client.get_context_window(session_id="probe", query="x")


def test_get_context_window_raises_when_daemon_missing(tmp_path):
    client = DaemonClient(tmp_path / "nope.sock", timeout=0.5)
    with pytest.raises(DaemonError):
        client.get_context_window(session_id="probe", query="x")


def test_read_memory_returns_payload(fake_daemon):
    payload = {
        "ok": True,
        "node_id": "n_bbb",
        "summary": "S",
        "detailed_summary": "D",
        "raw_turns": [{"role": "user", "text": "u"}, {"role": "assistant", "text": "a"}],
    }
    client, srv = fake_daemon({"read_memory": lambda _p: payload})
    got = client.read_memory("n_bbb", depth=2)
    assert got["summary"] == "S"
    assert got["raw_turns"][1]["role"] == "assistant"
    method, params = srv.calls[-1]
    assert method == "read_memory"
    assert params["depth"] == 2


def test_list_all_nodes_empty(fake_daemon):
    client, _ = fake_daemon({"list_all_nodes": lambda _p: {"ok": True, "nodes": []}})
    assert client.list_all_nodes() == []
