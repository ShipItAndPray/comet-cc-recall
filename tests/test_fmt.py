from __future__ import annotations

from comet_cc_recall.fmt import format_hits, format_node_read
from comet_cc_recall.recall import RecallHit


def _hit(**kw):
    base = dict(
        node_id="n_x",
        score=0.95,
        summary="redis SETNX race",
        trigger="idempotency keys",
        importance="HIGH",
        tags=("payments", "redis"),
        session_id="s1",
        created_at=1700000000.0,
    )
    base.update(kw)
    return RecallHit(**base)


def test_format_hits_includes_summary_and_tags():
    out = format_hits([_hit()], color=False)
    assert "n_x" in out
    assert "redis SETNX race" in out
    assert "trigger:" in out
    assert "payments, redis" in out
    assert "HIGH" in out
    # ANSI codes must not leak when color=False.
    assert "\x1b[" not in out


def test_format_hits_empty_message():
    out = format_hits([], color=False)
    assert "no recalled" in out


def test_format_node_read_summary_only():
    out = format_node_read({"node_id": "n_x", "summary": "S"}, color=False)
    assert "n_x" in out
    assert "summary:" in out
    assert "S" in out
    assert "raw turns:" not in out


def test_format_node_read_full_payload():
    payload = {
        "node_id": "n_x",
        "summary": "S",
        "detailed_summary": "D",
        "raw_turns": [
            {"role": "user", "text": "uu"},
            {"role": "assistant", "text": "aa"},
        ],
    }
    out = format_node_read(payload, color=False)
    assert "detailed:" in out
    assert "raw turns:" in out
    assert "[user] uu" in out
    assert "[assistant] aa" in out


def test_format_hits_color_on_emits_ansi():
    out = format_hits([_hit()], color=True)
    assert "\x1b[" in out
