from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from comet_cc_recall.client import DaemonError
from comet_cc_recall.recall import recall


@pytest.fixture
def repo_with_payments(fake_repo: Path, sample_python: Path) -> Path:
    target = fake_repo / "services" / "payments.py"
    target.parent.mkdir(parents=True)
    shutil.copy(sample_python, target)
    return target


def _node(node_id: str, summary: str, trigger: str = "", **kw):
    base = {
        "node_id": node_id,
        "summary": summary,
        "trigger": trigger,
        "topic_tags": kw.get("tags", []),
        "importance": kw.get("importance", "MED"),
        "session_id": kw.get("session_id", "s_test"),
        "created_at": kw.get("created_at", 1700000000.0),
    }
    return base


def test_recall_returns_hits_in_score_order(fake_daemon, repo_with_payments: Path):
    nodes = [
        _node("n_low", "unrelated cron job retry"),
        _node(
            "n_high",
            "fixed redis SETNX race in services/payments.py — myrepo deploy",
            trigger="idempotency key TTL shorter than retry interval",
            importance="HIGH",
        ),
        _node("n_mid", "myrepo deploy notes"),
    ]
    client, srv = fake_daemon({"get_context_window": lambda _p: {"ok": True, "nodes": nodes}})

    hits = recall(repo_with_payments, client=client, top_k=3)
    assert [h.node_id for h in hits[:1]] == ["n_high"]  # full path match wins
    # Repo-name match outranks the unrelated node.
    assert hits[1].node_id == "n_mid"
    # Scores must be monotonically non-increasing.
    assert all(hits[i].score >= hits[i + 1].score for i in range(len(hits) - 1))


def test_recall_passes_anchor_to_daemon(fake_daemon, repo_with_payments: Path):
    captured: dict[str, object] = {}

    def handler(p):
        captured.update(p)
        return {"ok": True, "nodes": []}

    client, _ = fake_daemon({"get_context_window": handler})
    recall(repo_with_payments, client=client)
    q = captured.get("query")
    assert isinstance(q, str)
    assert "repo:myrepo" in q
    assert "file:services/payments.py" in q
    assert "lang:python" in q
    assert "IdempotencyKey" in q


def test_recall_no_repo_filter(fake_daemon, repo_with_payments: Path):
    nodes = [
        _node("n1", "foo"),
        _node("n2", "bar — myrepo services/payments.py mention"),
    ]
    client, _ = fake_daemon({"get_context_window": lambda _p: {"ok": True, "nodes": nodes}})

    hits_with = recall(repo_with_payments, client=client, top_k=2, repo_filter=True)
    hits_without = recall(repo_with_payments, client=client, top_k=2, repo_filter=False)
    # With filter: n2 climbs above n1 thanks to repo bonus.
    assert hits_with[0].node_id == "n2"
    # Without filter: positional ranking only — n1 came first.
    assert hits_without[0].node_id == "n1"


def test_recall_dedupes_node_ids(fake_daemon, repo_with_payments: Path):
    nodes = [_node("n_dup", "first"), _node("n_dup", "duplicate")]
    client, _ = fake_daemon({"get_context_window": lambda _p: {"ok": True, "nodes": nodes}})
    hits = recall(repo_with_payments, client=client, top_k=5)
    assert len(hits) == 1
    assert hits[0].node_id == "n_dup"


def test_recall_unsupported_language_returns_empty(fake_daemon, tmp_path: Path):
    f = tmp_path / "notes.txt"
    f.write_text("scratch")
    client, srv = fake_daemon({"get_context_window": lambda _p: {"ok": True, "nodes": []}})
    hits = recall(f, client=client)
    assert hits == []
    # When the anchor is empty we shouldn't even hit the daemon.
    assert not any(m == "get_context_window" for m, _ in srv.calls)


def test_recall_propagates_daemon_error(fake_daemon, repo_with_payments: Path):
    client, _ = fake_daemon(
        {"get_context_window": lambda _p: {"ok": False, "error": "model died"}}
    )
    with pytest.raises(DaemonError, match="model died"):
        recall(repo_with_payments, client=client)


def test_recall_top_k_caps_results(fake_daemon, repo_with_payments: Path):
    nodes = [_node(f"n_{i}", f"summary {i}") for i in range(20)]
    client, _ = fake_daemon({"get_context_window": lambda _p: {"ok": True, "nodes": nodes}})
    hits = recall(repo_with_payments, client=client, top_k=4)
    assert len(hits) == 4


def test_recall_returns_dataclass_fields(fake_daemon, repo_with_payments: Path):
    nodes = [
        _node(
            "n_one",
            "summary text",
            trigger="trigger text",
            tags=["a", "b"],
            importance="HIGH",
            created_at=1700001234.5,
            session_id="s_abc",
        )
    ]
    client, _ = fake_daemon({"get_context_window": lambda _p: {"ok": True, "nodes": nodes}})
    hits = recall(repo_with_payments, client=client)
    h = hits[0]
    assert h.node_id == "n_one"
    assert h.summary == "summary text"
    assert h.trigger == "trigger text"
    assert h.importance == "HIGH"
    assert h.tags == ("a", "b")
    assert h.session_id == "s_abc"
    assert h.created_at == pytest.approx(1700001234.5)
    assert h.score > 0
