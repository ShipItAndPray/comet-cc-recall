from __future__ import annotations

import argparse
import json
import time

import pytest

from comet_cc_recall.cli_digest import add_subparser, cmd_digest
from comet_cc_recall.client import DaemonClient


def _node(nid, *, tags=(), importance="MED", summary="", created_at=None, parent_node_id=None):
    return {
        "node_id": nid,
        "summary": summary,
        "trigger": "",
        "topic_tags": list(tags),
        "importance": importance,
        "session_id": "s",
        "created_at": created_at if created_at is not None else time.time(),
        "parent_node_id": parent_node_id,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="comet-cc-recall")
    sub = parser.add_subparsers(dest="cmd")
    add_subparser(sub)
    return parser


def _run(argv, *, client=None):
    parser = _build_parser()
    args = parser.parse_args(argv)
    return cmd_digest(args, client=client)


def test_cli_digest_json_shape(fake_daemon, capsys):
    now = time.time()
    nodes = [
        _node("a", tags=["x"], importance="HIGH", created_at=now - 60, summary="alpha"),
        _node("b", tags=["x"], importance="HIGH", created_at=now - 120, summary="beta"),
        _node("c", tags=["x"], importance="LOW", created_at=now - 60, summary="charlie"),
    ]
    client, _ = fake_daemon({"list_all_nodes": lambda _p: {"ok": True, "nodes": nodes}})
    rc = _run(["digest", "--since", "7d", "--importance", "HIGH", "--json"], client=client)
    out = capsys.readouterr().out
    assert rc == 0
    payload = json.loads(out)
    assert set(payload.keys()) == {"since", "until", "total_nodes", "groups"}
    assert payload["total_nodes"] == 2
    assert len(payload["groups"]) == 1
    g = payload["groups"][0]
    assert g["tag"] == "x"
    assert g["total_in_period"] == 2
    assert {h["node_id"] for h in g["hits"]} == {"a", "b"}


def test_cli_digest_text_default(fake_daemon, capsys):
    now = time.time()
    nodes = [_node("n1", tags=["topicA"], summary="hello", created_at=now - 60)]
    client, _ = fake_daemon({"list_all_nodes": lambda _p: {"ok": True, "nodes": nodes}})
    rc = _run(["digest", "--color", "never"], client=client)
    out = capsys.readouterr().out
    assert rc == 0
    assert "digest:" in out
    assert "## topicA" in out
    assert "n1" in out
    assert "hello" in out


def test_cli_digest_md_output(fake_daemon, capsys):
    now = time.time()
    nodes = [_node("n1", tags=["topicA"], summary="hello", created_at=now - 60)]
    client, _ = fake_daemon({"list_all_nodes": lambda _p: {"ok": True, "nodes": nodes}})
    rc = _run(["digest", "-o", "md"], client=client)
    out = capsys.readouterr().out
    assert rc == 0
    assert out.startswith("# Digest")
    assert "## topicA (1)" in out


def test_cli_digest_top_per_tag(fake_daemon, capsys):
    now = time.time()
    nodes = [_node(f"n{i}", tags=["t"], created_at=now - 60 - i) for i in range(5)]
    client, _ = fake_daemon({"list_all_nodes": lambda _p: {"ok": True, "nodes": nodes}})
    rc = _run(["digest", "--top-per-tag", "2", "--json"], client=client)
    out = capsys.readouterr().out
    assert rc == 0
    payload = json.loads(out)
    g = payload["groups"][0]
    assert g["total_in_period"] == 5
    assert len(g["hits"]) == 2


def test_cli_digest_max_groups(fake_daemon, capsys):
    now = time.time()
    nodes = []
    for tag, count in [("a", 3), ("b", 2), ("c", 1)]:
        for i in range(count):
            nodes.append(_node(f"{tag}{i}", tags=[tag], created_at=now - 60 - i))
    client, _ = fake_daemon({"list_all_nodes": lambda _p: {"ok": True, "nodes": nodes}})
    rc = _run(["digest", "--max-groups", "2", "--json"], client=client)
    out = capsys.readouterr().out
    assert rc == 0
    payload = json.loads(out)
    assert [g["tag"] for g in payload["groups"]] == ["a", "b"]


def test_cli_digest_bad_since_returns_2(fake_daemon, capsys):
    client, _ = fake_daemon({"list_all_nodes": lambda _p: {"ok": True, "nodes": []}})
    rc = _run(["digest", "--since", "garbage"], client=client)
    err = capsys.readouterr().err
    assert rc == 2
    assert "since" in err.lower() or "unrecognized" in err.lower()


def test_cli_digest_daemon_unreachable_returns_3(tmp_path, capsys):
    client = DaemonClient(tmp_path / "nope.sock", timeout=0.5)
    rc = _run(["digest", "--since", "7d"], client=client)
    err = capsys.readouterr().err
    assert rc == 3
    assert "daemon" in err.lower()


def test_cli_digest_invalid_importance_choice(fake_daemon, capsys):
    client, _ = fake_daemon({"list_all_nodes": lambda _p: {"ok": True, "nodes": []}})
    with pytest.raises(SystemExit):
        _run(["digest", "--importance", "WAT"], client=client)


def test_cli_digest_repeated_importance(fake_daemon, capsys):
    now = time.time()
    nodes = [
        _node("h", tags=["t"], importance="HIGH", created_at=now - 60),
        _node("m", tags=["t"], importance="MED", created_at=now - 60),
        _node("l", tags=["t"], importance="LOW", created_at=now - 60),
    ]
    client, _ = fake_daemon({"list_all_nodes": lambda _p: {"ok": True, "nodes": nodes}})
    rc = _run(
        ["digest", "--importance", "HIGH", "--importance", "MED", "--json"],
        client=client,
    )
    out = capsys.readouterr().out
    assert rc == 0
    payload = json.loads(out)
    ids = {h["node_id"] for g in payload["groups"] for h in g["hits"]}
    assert ids == {"h", "m"}


def test_cli_digest_untagged_label_flag(fake_daemon, capsys):
    now = time.time()
    nodes = [_node("u", tags=[], created_at=now - 60)]
    client, _ = fake_daemon({"list_all_nodes": lambda _p: {"ok": True, "nodes": nodes}})
    rc = _run(["digest", "--untagged-label", "(none)", "--json"], client=client)
    out = capsys.readouterr().out
    assert rc == 0
    payload = json.loads(out)
    assert payload["groups"][-1]["tag"] == "(none)"
