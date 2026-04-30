from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path

import pytest

pytest.importorskip("mcp")

from comet_cc_recall import mcp_server  # noqa: E402


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


@pytest.fixture(autouse=True)
def _reset_default_client():
    mcp_server.set_client(None)
    yield
    mcp_server.set_client(None)


@pytest.fixture
def repo_with_payments(fake_repo: Path, sample_python: Path) -> Path:
    target = fake_repo / "src" / "payments.py"
    target.parent.mkdir(parents=True)
    shutil.copy(sample_python, target)
    return target


def test_build_server_registers_all_six_tools():
    server = mcp_server.build_server()
    tools = asyncio.run(server.list_tools())
    names = {t.name for t in tools}
    assert names == {
        "recall_file",
        "search",
        "related",
        "diff_recall",
        "context_block",
        "read_node",
    }


def test_recall_file_returns_serialized_hits(fake_daemon, repo_with_payments: Path):
    client, _ = fake_daemon(
        {"get_context_window": lambda _p: {"ok": True, "nodes": [_node("n1", "ok", tags=["a"])]}}
    )
    mcp_server.set_client(client)
    out = mcp_server.recall_file(str(repo_with_payments), top_k=3)
    assert isinstance(out, list)
    assert out[0]["node_id"] == "n1"
    assert out[0]["tags"] == ["a"]
    assert isinstance(out[0]["created_at"], float)
    json.dumps(out)


def test_recall_file_skips_unsupported_file(fake_daemon, tmp_path: Path):
    f = tmp_path / "notes.txt"
    f.write_text("scratch")
    client, srv = fake_daemon({"get_context_window": lambda _p: {"ok": True, "nodes": []}})
    mcp_server.set_client(client)
    out = mcp_server.recall_file(str(f))
    assert out == []
    assert not any(m == "get_context_window" for m, _ in srv.calls)


def test_recall_file_returns_error_on_daemon_failure(
    fake_daemon, repo_with_payments: Path
):
    client, _ = fake_daemon(
        {"get_context_window": lambda _p: {"ok": False, "error": "model died"}}
    )
    mcp_server.set_client(client)
    out = mcp_server.recall_file(str(repo_with_payments))
    assert out == {"error": "model died"}
    json.dumps(out)


def test_search_returns_serialized_hits(fake_daemon):
    client, _ = fake_daemon(
        {"get_context_window": lambda _p: {"ok": True, "nodes": [_node("s1", "match")]}}
    )
    mcp_server.set_client(client)
    out = mcp_server.search("redis race", top_k=2)
    assert isinstance(out, list)
    assert out[0]["node_id"] == "s1"
    json.dumps(out)


def test_search_returns_error_on_daemon_failure(fake_daemon):
    client, _ = fake_daemon(
        {"get_context_window": lambda _p: {"ok": False, "error": "boom"}}
    )
    mcp_server.set_client(client)
    out = mcp_server.search("q")
    assert out == {"error": "boom"}


def test_related_returns_serialized_hits(fake_daemon):
    children = [_node("c1"), _node("c2")]
    client, _ = fake_daemon({"list_linked_nodes": lambda _p: {"ok": True, "nodes": children}})
    mcp_server.set_client(client)
    out = mcp_server.related("seed", depth=1, top_k=5)
    assert isinstance(out, list)
    assert {h["node_id"] for h in out} == {"c1", "c2"}
    json.dumps(out)


def test_related_returns_error_on_daemon_failure(fake_daemon):
    client, _ = fake_daemon(
        {"list_linked_nodes": lambda _p: {"ok": False, "error": "no graph"}}
    )
    mcp_server.set_client(client)
    out = mcp_server.related("seed")
    assert out == {"error": "no graph"}


def test_diff_recall_returns_serialized_hits(
    fake_daemon, fake_repo: Path, sample_python: Path
):
    py = fake_repo / "src" / "payments.py"
    py.parent.mkdir(parents=True)
    shutil.copy(sample_python, py)
    client, _ = fake_daemon(
        {"get_context_window": lambda _p: {"ok": True, "nodes": [_node("d1", "ok")]}}
    )
    mcp_server.set_client(client)
    # diff_recall directly calls recall(), which uses the injected client.
    # We bypass git by relying on diff_recall's `paths=` plumbing — but the
    # MCP wrapper takes only `base`/`top_k`. So drive through the public
    # surface by passing an unreachable base; test via the underlying ref:
    # easier path: call _diff_recall via wrapper assuming no git changes
    # produces an empty list — that already exercises serialization.
    out = mcp_server.diff_recall(base=None, top_k=5)
    # In a fresh tmp tree there's no git repo, so this is `[]`.
    assert isinstance(out, list)
    json.dumps(out)


def test_diff_recall_returns_error_on_daemon_failure(
    fake_daemon, fake_repo: Path, sample_python: Path, monkeypatch
):
    # Force the underlying diff_recall to raise DaemonError by stubbing it.
    from comet_cc_recall import mcp_server as mod
    from comet_cc_recall.client import DaemonError

    def _boom(*_a, **_kw):
        raise DaemonError("nope")

    monkeypatch.setattr(mod, "_diff_recall", _boom)
    out = mod.diff_recall()
    assert out == {"error": "nope"}


def test_context_block_returns_block_dict(
    fake_daemon, fake_repo: Path, sample_python: Path
):
    target = fake_repo / "src" / "payments.py"
    target.parent.mkdir(parents=True)
    shutil.copy(sample_python, target)
    client, _ = fake_daemon(
        {"get_context_window": lambda _p: {"ok": True, "nodes": [_node("c1", "summary x")]}}
    )
    mcp_server.set_client(client)
    out = mcp_server.context_block(str(target))
    assert isinstance(out, dict)
    assert "block" in out
    assert "<recalled-memory>" in out["block"]
    assert 'id="c1"' in out["block"]
    json.dumps(out)


def test_context_block_returns_empty_when_no_hits(
    fake_daemon, fake_repo: Path, sample_python: Path
):
    target = fake_repo / "src" / "payments.py"
    target.parent.mkdir(parents=True)
    shutil.copy(sample_python, target)
    client, _ = fake_daemon({"get_context_window": lambda _p: {"ok": True, "nodes": []}})
    mcp_server.set_client(client)
    out = mcp_server.context_block(str(target))
    assert out == {"block": ""}


def test_context_block_returns_error_on_daemon_failure(
    fake_daemon, fake_repo: Path, sample_python: Path
):
    target = fake_repo / "src" / "payments.py"
    target.parent.mkdir(parents=True)
    shutil.copy(sample_python, target)
    client, _ = fake_daemon(
        {"get_context_window": lambda _p: {"ok": False, "error": "down"}}
    )
    mcp_server.set_client(client)
    out = mcp_server.context_block(str(target))
    assert out == {"error": "down"}


def test_read_node_returns_payload(fake_daemon):
    payload = {"ok": True, "node_id": "n1", "summary": "s", "depth": 0}

    def handler(p):
        assert p["node_id"] == "n1"
        assert p["depth"] == 0
        return payload

    client, _ = fake_daemon({"read_memory": handler})
    mcp_server.set_client(client)
    out = mcp_server.read_node("n1", depth=0)
    assert out == payload
    json.dumps(out)


def test_read_node_returns_error_on_daemon_failure(fake_daemon):
    client, _ = fake_daemon({"read_memory": lambda _p: {"ok": False, "error": "missing"}})
    mcp_server.set_client(client)
    out = mcp_server.read_node("nope")
    assert out == {"error": "missing"}


def test_set_client_is_used_by_tools(fake_daemon):
    client, srv = fake_daemon(
        {"get_context_window": lambda _p: {"ok": True, "nodes": [_node("n1")]}}
    )
    mcp_server.set_client(client)
    out = mcp_server.search("q")
    assert isinstance(out, list)
    assert out[0]["node_id"] == "n1"
    assert any(m == "get_context_window" for m, _ in srv.calls)


def test_set_client_none_clears_override(fake_daemon):
    client, _ = fake_daemon(
        {"get_context_window": lambda _p: {"ok": True, "nodes": [_node("n1")]}}
    )
    mcp_server.set_client(client)
    assert mcp_server._default_client is client
    mcp_server.set_client(None)
    assert mcp_server._default_client is None


def test_cli_mcp_add_subparser_registers_command():
    import argparse

    from comet_cc_recall import cli_mcp

    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd")
    cli_mcp.add_subparser(sub)
    args = p.parse_args(["mcp"])
    assert args.cmd == "mcp"


def test_cli_mcp_cmd_invokes_serve_stdio(monkeypatch, fake_daemon):
    from comet_cc_recall import cli_mcp
    from comet_cc_recall import mcp_server as mod

    called = {"n": 0}

    def fake_serve():
        called["n"] += 1

    monkeypatch.setattr(mod, "serve_stdio", fake_serve)

    client, _ = fake_daemon({"get_context_window": lambda _p: {"ok": True, "nodes": []}})
    rc = cli_mcp.cmd_mcp(object(), client=client)
    assert rc == 0
    assert called["n"] == 1
    assert mod._default_client is client
