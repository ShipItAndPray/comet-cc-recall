from __future__ import annotations

import time

import pytest

from comet_cc_recall.filters import filter_hits, parse_since
from comet_cc_recall.recall import RecallHit


def _hit(node_id="n", *, tags=(), importance="MED", created_at=None):
    return RecallHit(
        node_id=node_id,
        score=1.0,
        summary="",
        trigger="",
        importance=importance,
        tags=tuple(tags),
        session_id=None,
        created_at=created_at if created_at is not None else time.time(),
    )


def test_parse_since_duration_units():
    now = 1_700_000_000.0
    assert parse_since("60s", now=now) == now - 60
    assert parse_since("5m", now=now) == now - 300
    assert parse_since("2h", now=now) == now - 7200
    assert parse_since("1d", now=now) == now - 86_400
    assert parse_since("2w", now=now) == now - 1_209_600


def test_parse_since_iso_dates():
    cutoff = parse_since("2026-01-01")
    assert cutoff is not None
    assert cutoff > 0


def test_parse_since_none_or_empty():
    assert parse_since(None) is None
    assert parse_since("") is None
    assert parse_since("   ") is None


def test_parse_since_invalid_raises():
    with pytest.raises(ValueError):
        parse_since("nonsense")


def test_filter_by_tag_any_match():
    hits = [
        _hit("a", tags=("payments",)),
        _hit("b", tags=("auth",)),
        _hit("c", tags=("payments", "redis")),
    ]
    out = filter_hits(hits, tags=["payments"])
    assert {h.node_id for h in out} == {"a", "c"}


def test_filter_tag_case_insensitive():
    hits = [_hit("a", tags=("Payments",))]
    out = filter_hits(hits, tags=["PAYMENTS"])
    assert len(out) == 1


def test_filter_by_importance():
    hits = [_hit("h", importance="HIGH"), _hit("m", importance="MED"), _hit("l", importance="LOW")]
    assert {h.node_id for h in filter_hits(hits, importance=["HIGH"])} == {"h"}
    assert {h.node_id for h in filter_hits(hits, importance=["HIGH", "MED"])} == {"h", "m"}


def test_filter_invalid_importance_raises():
    hits = [_hit("a", importance="HIGH")]
    with pytest.raises(ValueError):
        filter_hits(hits, importance=["BOGUS"])


def test_filter_since_drops_old():
    now = time.time()
    hits = [
        _hit("recent", created_at=now - 60),
        _hit("old", created_at=now - 86_400 * 10),
    ]
    cutoff = now - 3600
    out = filter_hits(hits, since=cutoff)
    assert [h.node_id for h in out] == ["recent"]


def test_filter_combo():
    now = time.time()
    hits = [
        _hit("a", tags=("payments",), importance="HIGH", created_at=now - 60),
        _hit("b", tags=("payments",), importance="LOW", created_at=now - 60),
        _hit("c", tags=("payments",), importance="HIGH", created_at=now - 86_400 * 30),
    ]
    out = filter_hits(
        hits, tags=["payments"], importance=["HIGH"], since=now - 3600
    )
    assert [h.node_id for h in out] == ["a"]


def test_empty_filters_pass_through():
    hits = [_hit("a"), _hit("b")]
    out = filter_hits(hits)
    assert len(out) == 2
