"""CLI tests for v0.2 surfaces: search, related, diff, context, filters, formats."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from comet_cc_recall.cli import main


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


def _write_repo_file(fake_repo: Path, sample_python: Path) -> Path:
    target = fake_repo / "services" / "payments.py"
    target.parent.mkdir(parents=True)
    shutil.copy(sample_python, target)
    return target


def test_cli_search_pretty(fake_daemon, capsys):
    nodes = [_node("n1", "matched"), _node("n2", "second")]
    client, _ = fake_daemon({"get_context_window": lambda _p: {"ok": True, "nodes": nodes}})
    rc = main(["search", "redis race", "--color", "never"], client=client)
    out = capsys.readouterr().out
    assert rc == 0
    assert "n1" in out
    assert "matched" in out


def test_cli_search_md_output(fake_daemon, capsys):
    nodes = [_node("n1", "S")]
    client, _ = fake_daemon({"get_context_window": lambda _p: {"ok": True, "nodes": nodes}})
    rc = main(["search", "q", "-o", "md"], client=client)
    out = capsys.readouterr().out
    assert rc == 0
    assert "## `n1`" in out


def test_cli_recall_llm_format(fake_daemon, fake_repo, sample_python, capsys):
    target = _write_repo_file(fake_repo, sample_python)
    nodes = [_node("n1", "S", trigger="T")]
    client, _ = fake_daemon({"get_context_window": lambda _p: {"ok": True, "nodes": nodes}})
    rc = main(["recall", str(target), "-o", "llm"], client=client)
    out = capsys.readouterr().out
    assert rc == 0
    assert "<recalled-memory>" in out
    assert 'id="n1"' in out


def test_cli_recall_filter_by_tag(fake_daemon, fake_repo, sample_python, capsys):
    target = _write_repo_file(fake_repo, sample_python)
    nodes = [
        _node("a", "x", tags=["payments"]),
        _node("b", "x", tags=["auth"]),
    ]
    client, _ = fake_daemon({"get_context_window": lambda _p: {"ok": True, "nodes": nodes}})
    rc = main(["recall", str(target), "--tag", "payments", "--json"], client=client)
    out = capsys.readouterr().out
    assert rc == 0
    payload = json.loads(out)
    assert [h["node_id"] for h in payload] == ["a"]


def test_cli_recall_filter_by_importance(fake_daemon, fake_repo, sample_python, capsys):
    target = _write_repo_file(fake_repo, sample_python)
    nodes = [
        _node("a", "x", importance="HIGH"),
        _node("b", "x", importance="LOW"),
    ]
    client, _ = fake_daemon({"get_context_window": lambda _p: {"ok": True, "nodes": nodes}})
    rc = main(
        ["recall", str(target), "--importance", "HIGH", "--json"], client=client
    )
    out = capsys.readouterr().out
    assert rc == 0
    payload = json.loads(out)
    assert [h["node_id"] for h in payload] == ["a"]


def test_cli_search_filter_by_since(fake_daemon, capsys):
    import time

    now = time.time()
    nodes = [
        _node("recent", created_at=now - 60),
        _node("old", created_at=now - 86_400 * 30),
    ]
    client, _ = fake_daemon({"get_context_window": lambda _p: {"ok": True, "nodes": nodes}})
    rc = main(["search", "q", "--since", "1h", "--json"], client=client)
    out = capsys.readouterr().out
    assert rc == 0
    payload = json.loads(out)
    assert [h["node_id"] for h in payload] == ["recent"]


def test_cli_since_invalid_returns_2(fake_daemon, capsys):
    client, _ = fake_daemon({"get_context_window": lambda _p: {"ok": True, "nodes": []}})
    rc = main(["search", "q", "--since", "garbage"], client=client)
    err = capsys.readouterr().err
    assert rc == 2
    assert "since" in err.lower() or "unrecognized" in err.lower()


def test_cli_related(fake_daemon, capsys):
    nodes = [_node("c1", "child"), _node("c2", "child2")]
    client, _ = fake_daemon({"list_linked_nodes": lambda _p: {"ok": True, "nodes": nodes}})
    rc = main(["related", "n_seed", "--depth", "1", "--color", "never"], client=client)
    out = capsys.readouterr().out
    assert rc == 0
    assert "c1" in out
    assert "c2" in out


def test_cli_diff_paths_overridden_via_recall_pipeline(
    fake_daemon, fake_repo, sample_python, monkeypatch, capsys
):
    """`diff` should call get_context_window once per supported changed file."""
    target = _write_repo_file(fake_repo, sample_python)
    # Stub git: pretend exactly one file changed.
    from comet_cc_recall import diff as diffmod

    def fake_changed_files(_base=None, **_kw):
        return [target]

    monkeypatch.setattr(diffmod, "changed_files", fake_changed_files)

    nodes = [_node("n_diff", "from diff")]
    client, _ = fake_daemon({"get_context_window": lambda _p: {"ok": True, "nodes": nodes}})

    rc = main(["diff", "--color", "never"], client=client)
    out = capsys.readouterr().out
    assert rc == 0
    assert "n_diff" in out


def test_cli_context_emits_block(fake_daemon, fake_repo, sample_python, capsys):
    target = _write_repo_file(fake_repo, sample_python)
    nodes = [_node("nc", "summary text")]
    client, _ = fake_daemon({"get_context_window": lambda _p: {"ok": True, "nodes": nodes}})

    rc = main(["context", str(target)], client=client)
    out = capsys.readouterr().out
    assert rc == 0
    assert "<recalled-memory>" in out
    assert 'id="nc"' in out


def test_cli_context_empty_block(fake_daemon, fake_repo, sample_python, capsys):
    target = _write_repo_file(fake_repo, sample_python)
    client, _ = fake_daemon({"get_context_window": lambda _p: {"ok": True, "nodes": []}})
    rc = main(["context", str(target)], client=client)
    out = capsys.readouterr().out
    assert rc == 0
    assert "<empty/>" in out


def test_cli_context_missing_file_rc2(capsys):
    rc = main(["context", "/no/such/file.py"])
    err = capsys.readouterr().err
    assert rc == 2
    assert "file not found" in err
