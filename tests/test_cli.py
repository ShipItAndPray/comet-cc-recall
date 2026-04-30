from __future__ import annotations

import json
import shutil
from pathlib import Path

from comet_cc_recall.cli import main


def _write_repo_file(fake_repo: Path, sample_python: Path) -> Path:
    target = fake_repo / "services" / "payments.py"
    target.parent.mkdir(parents=True)
    shutil.copy(sample_python, target)
    return target


def test_cli_recall_pretty(fake_daemon, fake_repo, sample_python, capsys):
    target = _write_repo_file(fake_repo, sample_python)
    nodes = [
        {
            "node_id": "n_aaa",
            "summary": "redis race",
            "trigger": "TTL collisions",
            "topic_tags": ["payments"],
            "importance": "HIGH",
            "session_id": "s1",
            "created_at": 1700000000.0,
        }
    ]
    client, _ = fake_daemon({"get_context_window": lambda _p: {"ok": True, "nodes": nodes}})

    rc = main(["recall", str(target), "--color", "never"], client=client)
    out = capsys.readouterr().out
    assert rc == 0
    assert "n_aaa" in out
    assert "redis race" in out
    assert "TTL collisions" in out


def test_cli_recall_json(fake_daemon, fake_repo, sample_python, capsys):
    target = _write_repo_file(fake_repo, sample_python)
    nodes = [
        {
            "node_id": "n_aaa",
            "summary": "S",
            "trigger": "T",
            "topic_tags": ["a"],
            "importance": "MED",
            "session_id": "sx",
            "created_at": 0.0,
        }
    ]
    client, _ = fake_daemon({"get_context_window": lambda _p: {"ok": True, "nodes": nodes}})

    rc = main(["recall", str(target), "--json"], client=client)
    out = capsys.readouterr().out
    assert rc == 0
    payload = json.loads(out)
    assert isinstance(payload, list)
    assert payload[0]["node_id"] == "n_aaa"
    assert payload[0]["tags"] == ["a"]


def test_cli_missing_file(capsys):
    rc = main(["recall", "/no/such/file.py"])
    err = capsys.readouterr().err
    assert rc == 2
    assert "file not found" in err


def test_cli_daemon_unreachable(tmp_path, sample_python, capsys):
    from comet_cc_recall.client import DaemonClient

    client = DaemonClient(tmp_path / "nope.sock", timeout=0.5)
    rc = main(["recall", str(sample_python), "--color", "never"], client=client)
    err = capsys.readouterr().err
    assert rc == 3
    assert "daemon" in err.lower()


def test_cli_doctor_no_daemon(tmp_path, capsys):
    from comet_cc_recall.client import DaemonClient

    client = DaemonClient(tmp_path / "nope.sock", timeout=0.5)
    rc = main(["doctor"], client=client)
    out = capsys.readouterr().out
    assert rc == 1
    assert "socket exists: False" in out


def test_cli_doctor_with_daemon(fake_daemon, capsys):
    client, _ = fake_daemon({"ping": lambda _p: {"ok": True}})
    rc = main(["doctor"], client=client)
    out = capsys.readouterr().out
    assert rc == 0
    assert "daemon ping: True" in out


def test_cli_read_summary(fake_daemon, capsys):
    client, _ = fake_daemon(
        {"read_memory": lambda _p: {"ok": True, "node_id": "n_x", "summary": "hello"}}
    )
    rc = main(["read", "n_x", "--depth", "0", "--color", "never"], client=client)
    out = capsys.readouterr().out
    assert rc == 0
    assert "hello" in out
    assert "n_x" in out


def test_cli_read_raw_turns(fake_daemon, capsys):
    payload = {
        "ok": True,
        "node_id": "n_x",
        "summary": "S",
        "raw_turns": [
            {"role": "user", "text": "u1"},
            {"role": "assistant", "text": "a1"},
        ],
    }
    client, _ = fake_daemon({"read_memory": lambda _p: payload})
    rc = main(["read", "n_x", "--depth", "2", "--color", "never"], client=client)
    out = capsys.readouterr().out
    assert rc == 0
    assert "[user]" in out
    assert "u1" in out
    assert "[assistant]" in out
    assert "a1" in out


def test_cli_bare_path_invokes_recall(fake_daemon, fake_repo, sample_python, capsys):
    target = _write_repo_file(fake_repo, sample_python)
    nodes = [
        {
            "node_id": "n_bare",
            "summary": "from bare invocation",
            "trigger": "",
            "topic_tags": [],
            "importance": "LOW",
            "session_id": None,
            "created_at": 0.0,
        }
    ]
    client, _ = fake_daemon({"get_context_window": lambda _p: {"ok": True, "nodes": nodes}})
    rc = main([str(target)], client=client)
    out = capsys.readouterr().out
    assert rc == 0
    assert "n_bare" in out


def test_cli_help_no_args(capsys):
    rc = main([])
    out = capsys.readouterr().out
    assert rc == 0
    assert "comet-cc-recall" in out
