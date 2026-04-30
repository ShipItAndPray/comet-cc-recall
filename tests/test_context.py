from __future__ import annotations

import shutil
from pathlib import Path

from comet_cc_recall.context import context_block


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


def test_context_block_emits_recalled_memory_block(
    fake_daemon, fake_repo: Path, sample_python: Path
):
    target = fake_repo / "src" / "payments.py"
    target.parent.mkdir(parents=True)
    shutil.copy(sample_python, target)

    client, _ = fake_daemon(
        {"get_context_window": lambda _p: {"ok": True, "nodes": [_node("n1", "redis race")]}}
    )
    block = context_block(target, client=client)
    assert "<recalled-memory>" in block
    assert "</recalled-memory>" in block
    assert "<anchor>" in block
    assert "<instruction>" in block
    assert 'id="n1"' in block
    assert "redis race" in block


def test_context_block_empty_when_no_hits(fake_daemon, fake_repo: Path, sample_python: Path):
    target = fake_repo / "src" / "payments.py"
    target.parent.mkdir(parents=True)
    shutil.copy(sample_python, target)
    client, _ = fake_daemon({"get_context_window": lambda _p: {"ok": True, "nodes": []}})
    out = context_block(target, client=client)
    assert out == ""


def test_context_block_for_unsupported_file_returns_empty(fake_daemon, tmp_path: Path):
    f = tmp_path / "notes.txt"
    f.write_text("scratch")
    client, _ = fake_daemon({"get_context_window": lambda _p: {"ok": True, "nodes": []}})
    assert context_block(f, client=client) == ""
