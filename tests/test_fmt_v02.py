from __future__ import annotations

import json

from comet_cc_recall.fmt import (
    format_hits_any,
    format_hits_json,
    format_hits_llm,
    format_hits_markdown,
)
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


def test_markdown_card_contains_id_and_summary():
    out = format_hits_markdown([_hit()])
    assert "## `n_x`" in out
    assert "redis SETNX race" in out
    assert "**trigger:**" in out
    assert "`payments`" in out


def test_markdown_with_heading():
    out = format_hits_markdown([_hit()], heading="recall: foo.py")
    assert out.startswith("# recall: foo.py")


def test_markdown_empty():
    out = format_hits_markdown([])
    assert "no recalled" in out


def test_llm_block_shape():
    out = format_hits_llm([_hit()], anchor="repo:r | file:x.py", instruction="treat as ctx")
    assert out.startswith("<recalled-memory>")
    assert out.endswith("</recalled-memory>")
    assert "<anchor>repo:r | file:x.py</anchor>" in out
    assert "<instruction>treat as ctx</instruction>" in out
    assert 'id="n_x"' in out
    assert 'importance="HIGH"' in out
    assert "<summary>redis SETNX race</summary>" in out
    assert "<trigger>idempotency keys</trigger>" in out


def test_llm_empty_emits_empty_self_close():
    out = format_hits_llm([])
    assert "<empty/>" in out


def test_json_format_round_trips():
    out = format_hits_json([_hit()])
    parsed = json.loads(out)
    assert parsed[0]["node_id"] == "n_x"
    assert parsed[0]["importance"] == "HIGH"
    assert parsed[0]["tags"] == ["payments", "redis"]


def test_dispatcher_routes_correctly():
    h = [_hit()]
    assert "{" in format_hits_any(h, fmt="json")
    assert "## `n_x`" in format_hits_any(h, fmt="md")
    assert "<recalled-memory>" in format_hits_any(h, fmt="llm")
    assert "n_x" in format_hits_any(h, fmt="text", color=False)


def test_dispatcher_unknown_format_raises():
    import pytest

    with pytest.raises(ValueError):
        format_hits_any([_hit()], fmt="bogus")
