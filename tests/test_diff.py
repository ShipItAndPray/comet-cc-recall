from __future__ import annotations

import shutil
from pathlib import Path

from comet_cc_recall.diff import changed_files, diff_recall


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


def _make_runner(toplevel: Path, *, diff_files: list[str], untracked: list[str] | None = None):
    """Stub out subprocess.run for git invocations."""

    class R:
        def __init__(self, returncode, stdout):
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = ""

    def runner(cmd, *_, **__):
        if cmd[:2] == ["git", "rev-parse"]:
            return R(0, str(toplevel) + "\n")
        if "diff" in cmd:
            return R(0, "\n".join(diff_files) + "\n")
        if "ls-files" in cmd:
            return R(0, "\n".join(untracked or []) + "\n")
        return R(1, "")

    return runner


def test_changed_files_outside_repo_returns_empty(tmp_path: Path):
    def runner(*_, **__):
        class R:
            returncode = 128
            stdout = ""
            stderr = "not a git repo"
        return R()

    files = changed_files(cwd=tmp_path, runner=runner)
    assert files == []


def test_changed_files_resolves_paths(fake_repo: Path, sample_python: Path):
    target = fake_repo / "services" / "payments.py"
    target.parent.mkdir(parents=True)
    shutil.copy(sample_python, target)
    runner = _make_runner(fake_repo, diff_files=["services/payments.py"])
    files = changed_files(base="HEAD", cwd=fake_repo, runner=runner)
    assert files == [target]


def test_changed_files_skips_missing(fake_repo: Path):
    runner = _make_runner(fake_repo, diff_files=["does/not/exist.py"])
    assert changed_files(base="HEAD", cwd=fake_repo, runner=runner) == []


def test_diff_recall_merges_hits_across_files(
    fake_daemon, fake_repo: Path, sample_python: Path, sample_typescript: Path
):
    py = fake_repo / "src" / "payments.py"
    py.parent.mkdir(parents=True)
    shutil.copy(sample_python, py)
    ts = fake_repo / "src" / "auth.ts"
    shutil.copy(sample_typescript, ts)

    nodes = [_node("shared", "matches both files"), _node("py-only", "payments specific")]
    client, _ = fake_daemon({"get_context_window": lambda _p: {"ok": True, "nodes": nodes}})

    hits = diff_recall(client=client, top_k=10, paths=[py, ts])
    ids = [h.node_id for h in hits]
    # Dedup: each id appears only once.
    assert sorted(ids) == sorted(set(ids))
    assert "shared" in ids
    assert "py-only" in ids


def test_diff_recall_skips_unsupported_files(
    fake_daemon, fake_repo: Path, sample_python: Path, tmp_path: Path
):
    py = fake_repo / "src" / "payments.py"
    py.parent.mkdir(parents=True)
    shutil.copy(sample_python, py)
    txt = fake_repo / "notes.txt"
    txt.write_text("scratch")

    nodes = [_node("only", "summary")]
    client, srv = fake_daemon({"get_context_window": lambda _p: {"ok": True, "nodes": nodes}})

    hits = diff_recall(client=client, top_k=10, paths=[py, txt])
    assert [h.node_id for h in hits] == ["only"]
    # Only one daemon call (for the .py file).
    assert sum(1 for m, _ in srv.calls if m == "get_context_window") == 1


def test_diff_recall_no_paths_returns_empty(fake_daemon):
    client, _ = fake_daemon({"get_context_window": lambda _p: {"ok": True, "nodes": []}})
    assert diff_recall(client=client, paths=[]) == []
