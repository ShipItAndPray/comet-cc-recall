from __future__ import annotations

import json
import time

import pytest

from comet_cc_recall.client import DaemonError
from comet_cc_recall.digest import (
    Digest,
    DigestGroup,
    digest,
    format_digest_json,
    format_digest_md,
    format_digest_text,
)


def _node(
    nid: str,
    *,
    summary: str = "",
    trigger: str = "",
    tags=(),
    importance: str = "MED",
    session_id: str = "s",
    created_at: float | None = None,
    parent_node_id=None,
):
    return {
        "node_id": nid,
        "summary": summary,
        "trigger": trigger,
        "topic_tags": list(tags),
        "importance": importance,
        "session_id": session_id,
        "created_at": created_at if created_at is not None else time.time(),
        "parent_node_id": parent_node_id,
    }


def _serve(fake_daemon, nodes):
    return fake_daemon({"list_all_nodes": lambda _p: {"ok": True, "nodes": nodes}})


def test_digest_empty_store_returns_empty(fake_daemon):
    client, _ = _serve(fake_daemon, [])
    d = digest(client=client, since="7d")
    assert isinstance(d, Digest)
    assert d.total_nodes == 0
    assert d.groups == ()
    assert d.until > d.since


def test_digest_period_filter_excludes_old(fake_daemon):
    now = time.time()
    nodes = [
        _node("recent", tags=["a"], created_at=now - 60),
        _node("old", tags=["a"], created_at=now - 86_400 * 30),
    ]
    client, _ = _serve(fake_daemon, nodes)
    d = digest(client=client, since="1d")
    assert d.total_nodes == 1
    assert len(d.groups) == 1
    assert {h.node_id for h in d.groups[0].hits} == {"recent"}


def test_digest_importance_filter(fake_daemon):
    now = time.time()
    nodes = [
        _node("h", tags=["x"], importance="HIGH", created_at=now - 60),
        _node("m", tags=["x"], importance="MED", created_at=now - 60),
        _node("l", tags=["x"], importance="LOW", created_at=now - 60),
    ]
    client, _ = _serve(fake_daemon, nodes)
    d = digest(client=client, since="1d", importance=["HIGH"])
    assert d.total_nodes == 1
    assert d.groups[0].hits[0].node_id == "h"


def test_digest_multi_tag_node_assigned_to_highest_freq_tag(fake_daemon):
    now = time.time()
    nodes = [_node(f"only_b_{i}", tags=["b"], created_at=now - 60) for i in range(5)]
    nodes.append(_node("multi", tags=["a", "b"], created_at=now - 60))
    nodes.append(_node("only_a", tags=["a"], created_at=now - 60))

    client, _ = _serve(fake_daemon, nodes)
    d = digest(client=client, since="1d", top_per_tag=10)

    by_tag = {g.tag: g for g in d.groups}
    assert "b" in by_tag
    assert "a" in by_tag
    assert "multi" in {h.node_id for h in by_tag["b"].hits}
    assert "multi" not in {h.node_id for h in by_tag["a"].hits}
    assert by_tag["b"].total_in_period == 6
    assert by_tag["a"].total_in_period == 1


def test_digest_multi_tag_tie_broken_alphabetically(fake_daemon):
    now = time.time()
    nodes = [
        _node("multi", tags=["zebra", "apple"], created_at=now - 60),
    ]
    client, _ = _serve(fake_daemon, nodes)
    d = digest(client=client, since="1d", top_per_tag=10)
    tag_for_multi = {g.tag for g in d.groups if "multi" in {h.node_id for h in g.hits}}
    assert tag_for_multi == {"apple"}


def test_digest_top_per_tag_truncates_but_total_reflects_full(fake_daemon):
    now = time.time()
    nodes = [
        _node(f"n{i}", tags=["t"], created_at=now - 60 - i)
        for i in range(7)
    ]
    client, _ = _serve(fake_daemon, nodes)
    d = digest(client=client, since="1d", top_per_tag=3)
    assert len(d.groups) == 1
    g = d.groups[0]
    assert g.total_in_period == 7
    assert len(g.hits) == 3


def test_digest_max_groups_caps_groups(fake_daemon):
    now = time.time()
    nodes = []
    for tag, count in [("a", 4), ("b", 3), ("c", 2), ("d", 1)]:
        for i in range(count):
            nodes.append(_node(f"{tag}{i}", tags=[tag], created_at=now - 60 - i))
    client, _ = _serve(fake_daemon, nodes)
    d = digest(client=client, since="1d", max_groups=2, top_per_tag=10)
    assert [g.tag for g in d.groups] == ["a", "b"]


def test_digest_untagged_bucket(fake_daemon):
    now = time.time()
    nodes = [
        _node("u1", tags=[], created_at=now - 60),
        _node("u2", tags=[], created_at=now - 120),
        _node("t1", tags=["x"], created_at=now - 60),
    ]
    client, _ = _serve(fake_daemon, nodes)
    d = digest(client=client, since="1d", top_per_tag=10)
    tags = [g.tag for g in d.groups]
    assert tags[-1] == "_untagged"
    untagged = d.groups[-1]
    assert {h.node_id for h in untagged.hits} == {"u1", "u2"}
    assert untagged.total_in_period == 2


def test_digest_untagged_label_custom(fake_daemon):
    now = time.time()
    nodes = [_node("u", tags=[], created_at=now - 60)]
    client, _ = _serve(fake_daemon, nodes)
    d = digest(client=client, since="1d", untagged_label="(none)")
    assert d.groups[-1].tag == "(none)"


def test_digest_excludes_children_with_parent_node_id(fake_daemon):
    now = time.time()
    nodes = [
        _node("parent", tags=["x"], created_at=now - 60),
        _node("child", tags=["x"], created_at=now - 60, parent_node_id="parent"),
    ]
    client, _ = _serve(fake_daemon, nodes)
    d = digest(client=client, since="1d", top_per_tag=10)
    all_ids = [h.node_id for g in d.groups for h in g.hits]
    assert "child" not in all_ids
    assert "parent" in all_ids
    assert d.total_nodes == 1


def test_digest_groups_sorted_by_size_then_tag(fake_daemon):
    now = time.time()
    nodes = [
        _node("a1", tags=["alpha"], created_at=now - 60),
        _node("b1", tags=["bravo"], created_at=now - 60),
        _node("b2", tags=["bravo"], created_at=now - 60),
        _node("c1", tags=["charlie"], created_at=now - 60),
        _node("c2", tags=["charlie"], created_at=now - 60),
    ]
    client, _ = _serve(fake_daemon, nodes)
    d = digest(client=client, since="1d", top_per_tag=10)
    tags_in_order = [g.tag for g in d.groups]
    assert tags_in_order == ["bravo", "charlie", "alpha"]


def test_digest_hits_sorted_by_importance_then_recency(fake_daemon):
    now = time.time()
    nodes = [
        _node("low_new", tags=["t"], importance="LOW", created_at=now - 60),
        _node("high_old", tags=["t"], importance="HIGH", created_at=now - 600),
        _node("med_new", tags=["t"], importance="MED", created_at=now - 60),
        _node("high_new", tags=["t"], importance="HIGH", created_at=now - 30),
    ]
    client, _ = _serve(fake_daemon, nodes)
    d = digest(client=client, since="1d", top_per_tag=10)
    order = [h.node_id for h in d.groups[0].hits]
    assert order == ["high_new", "high_old", "med_new", "low_new"]


def test_digest_propagates_daemon_error(fake_daemon):
    client, _ = fake_daemon(
        {"list_all_nodes": lambda _p: {"ok": False, "error": "boom"}}
    )
    with pytest.raises(DaemonError):
        digest(client=client, since="1d")


def test_format_digest_text_includes_counts_and_ids(fake_daemon):
    now = time.time()
    nodes = [
        _node("n1", summary="alpha summary", tags=["topicA"], created_at=now - 60),
        _node("n2", summary="beta summary", tags=["topicA"], created_at=now - 90),
    ]
    client, _ = _serve(fake_daemon, nodes)
    d = digest(client=client, since="1d")
    out = format_digest_text(d, color=False)
    assert "digest: 2 nodes" in out
    assert "## topicA" in out
    assert "(2)" in out
    assert "n1" in out and "n2" in out
    assert "alpha summary" in out


def test_format_digest_text_empty(fake_daemon):
    client, _ = _serve(fake_daemon, [])
    d = digest(client=client, since="1d")
    out = format_digest_text(d, color=False)
    assert "digest: 0 nodes" in out
    assert "no groups" in out


def test_format_digest_md_valid_structure(fake_daemon):
    now = time.time()
    nodes = [
        _node("n1", summary="hello", tags=["topicA"], created_at=now - 60),
    ]
    client, _ = _serve(fake_daemon, nodes)
    d = digest(client=client, since="1d")
    out = format_digest_md(d)
    assert out.startswith("# Digest")
    assert "## topicA (1)" in out
    assert "- `n1` **MED** — hello" in out
    assert out.endswith("\n")


def test_format_digest_md_empty(fake_daemon):
    client, _ = _serve(fake_daemon, [])
    d = digest(client=client, since="1d")
    out = format_digest_md(d)
    assert "# Digest" in out
    assert "_no groups_" in out


def test_format_digest_md_toc_when_many_groups(fake_daemon):
    now = time.time()
    nodes = []
    for tag in ["a", "b", "c", "d", "e", "f"]:
        nodes.append(_node(f"n_{tag}", tags=[tag], created_at=now - 60))
    client, _ = _serve(fake_daemon, nodes)
    d = digest(client=client, since="1d")
    out = format_digest_md(d)
    assert "## Contents" in out
    for tag in ["a", "b", "c", "d", "e", "f"]:
        assert f"- [{tag}](#{tag})" in out


def test_format_digest_md_no_toc_for_few_groups(fake_daemon):
    now = time.time()
    nodes = [_node(f"n_{t}", tags=[t], created_at=now - 60) for t in ["a", "b"]]
    client, _ = _serve(fake_daemon, nodes)
    d = digest(client=client, since="1d")
    out = format_digest_md(d)
    assert "## Contents" not in out


def test_format_digest_json_roundtrips(fake_daemon):
    now = time.time()
    nodes = [
        _node("n1", summary="s1", trigger="t1", tags=["a"], created_at=now - 60),
        _node("n2", summary="s2", tags=["a"], created_at=now - 120),
    ]
    client, _ = _serve(fake_daemon, nodes)
    d = digest(client=client, since="1d")
    raw = format_digest_json(d)
    payload = json.loads(raw)
    assert set(payload.keys()) == {"since", "until", "total_nodes", "groups"}
    assert payload["total_nodes"] == 2
    assert len(payload["groups"]) == 1
    g = payload["groups"][0]
    assert g["tag"] == "a"
    assert g["total_in_period"] == 2
    assert {h["node_id"] for h in g["hits"]} == {"n1", "n2"}
    sample_hit = g["hits"][0]
    expected_fields = {
        "node_id",
        "summary",
        "trigger",
        "importance",
        "tags",
        "session_id",
        "created_at",
    }
    assert expected_fields.issubset(sample_hit.keys())


def test_digest_group_dataclass_frozen():
    from dataclasses import FrozenInstanceError

    g = DigestGroup(tag="x", hits=(), total_in_period=0)
    with pytest.raises(FrozenInstanceError):
        g.tag = "y"  # type: ignore[misc]


def test_digest_until_override(fake_daemon):
    now = time.time()
    nodes = [
        _node("a", tags=["t"], created_at=now - 60),
        _node("b", tags=["t"], created_at=now - 5),
    ]
    client, _ = _serve(fake_daemon, nodes)
    d = digest(client=client, since="1d", until=now - 30, top_per_tag=10)
    ids = {h.node_id for g in d.groups for h in g.hits}
    assert ids == {"a"}
    assert d.until == now - 30


def test_format_digest_text_truncates_long_summary(fake_daemon):
    now = time.time()
    long_summary = "x" * 500
    nodes = [_node("big", summary=long_summary, tags=["t"], created_at=now - 60)]
    client, _ = _serve(fake_daemon, nodes)
    d = digest(client=client, since="1d")
    out = format_digest_text(d, color=False)
    assert "…" in out


def test_format_digest_text_with_color(fake_daemon):
    now = time.time()
    nodes = [_node("n1", summary="s", tags=["t"], created_at=now - 60)]
    client, _ = _serve(fake_daemon, nodes)
    d = digest(client=client, since="1d")
    out = format_digest_text(d, color=True)
    assert "\x1b[" in out


def test_digest_since_empty_string_uses_zero_cutoff(fake_daemon):
    now = time.time()
    nodes = [
        _node("ancient", tags=["t"], created_at=now - 86_400 * 365 * 5),
    ]
    client, _ = _serve(fake_daemon, nodes)
    d = digest(client=client, since="")
    assert d.since == 0.0
    assert d.total_nodes == 1


def test_format_digest_any_dispatch(fake_daemon):
    from comet_cc_recall.digest import format_digest_any

    now = time.time()
    nodes = [_node("n1", tags=["t"], summary="s", created_at=now - 60)]
    client, _ = _serve(fake_daemon, nodes)
    d = digest(client=client, since="1d")
    assert "Digest" in format_digest_any(d, fmt="md")
    payload = json.loads(format_digest_any(d, fmt="json"))
    assert payload["total_nodes"] == 1
    assert "n1" in format_digest_any(d, fmt="text", color=False)
    with pytest.raises(ValueError):
        format_digest_any(d, fmt="bogus")


def test_format_digest_text_supports_color_default(fake_daemon, monkeypatch):
    now = time.time()
    nodes = [_node("n1", tags=["t"], summary="s", created_at=now - 60)]
    client, _ = _serve(fake_daemon, nodes)
    d = digest(client=client, since="1d")

    class _NotATTY:
        def isatty(self) -> bool:
            return False

    from comet_cc_recall import digest as digest_mod

    monkeypatch.setattr(digest_mod.sys, "stdout", _NotATTY())
    out = format_digest_text(d)
    assert "\x1b[" not in out


def test_isodate_zero_returns_empty():
    from comet_cc_recall.digest import _isodate

    assert _isodate(0.0) == ""
