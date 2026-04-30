"""Tests for the git pre-push hook installer and its CLI surface."""

from __future__ import annotations

import argparse
import re
import stat
from pathlib import Path

import pytest

from comet_cc_recall import hook as hookmod
from comet_cc_recall.cli_hook import add_subparser, cmd_hook
from comet_cc_recall.hook import (
    HookError,
    InstallResult,
    StatusResult,
    UninstallResult,
    install,
    status,
    uninstall,
)

# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


def _make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / ".git" / "hooks").mkdir(parents=True)
    return repo


def _hook(repo: Path, name: str = "pre-push") -> Path:
    return repo / ".git" / "hooks" / name


def _ok_runner(toplevel: Path):
    """A subprocess.run stub that always reports `toplevel` as the repo root."""

    class R:
        def __init__(self, returncode: int, stdout: str) -> None:
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = ""

    def runner(cmd, *_, **__):
        if cmd[:2] == ["git", "rev-parse"]:
            return R(0, str(toplevel) + "\n")
        return R(1, "")

    return runner


def _bad_runner(*_, **__):
    class R:
        returncode = 128
        stdout = ""
        stderr = "fatal: not a git repository"

    return R()


def _missing_git_runner(*_, **__):
    raise FileNotFoundError("git not on PATH")


def _count_blocks(content: str) -> int:
    return len(
        re.findall(
            re.escape("# >>> comet-cc-recall (managed) >>>")
            + r".*?"
            + re.escape("# <<< comet-cc-recall (managed) <<<"),
            content,
            re.DOTALL,
        )
    )


# --------------------------------------------------------------------------- #
# install()                                                                   #
# --------------------------------------------------------------------------- #


def test_install_creates_new_hook_file(tmp_path: Path):
    repo = _make_repo(tmp_path)
    res = install(repo_root=repo)
    assert isinstance(res, InstallResult)
    assert res.installed is True
    assert res.already_present is False
    assert res.executable is True
    content = _hook(repo).read_text(encoding="utf-8")
    assert content.startswith("#!/bin/sh")
    assert _count_blocks(content) == 1
    # File mode includes executable bits.
    mode = _hook(repo).stat().st_mode
    assert mode & stat.S_IXUSR


def test_install_appends_to_existing_user_hook(tmp_path: Path):
    repo = _make_repo(tmp_path)
    existing = "#!/usr/bin/env bash\n# user-defined logic\necho 'pushing!'\n"
    _hook(repo).write_text(existing, encoding="utf-8")

    res = install(repo_root=repo)
    assert res.installed is True
    assert res.already_present is False
    new_content = _hook(repo).read_text(encoding="utf-8")
    # User content preserved verbatim.
    assert existing in new_content
    # Our block appears exactly once, after the user content.
    assert _count_blocks(new_content) == 1
    assert new_content.index("# user-defined logic") < new_content.index(
        "# >>> comet-cc-recall (managed) >>>"
    )


def test_install_is_idempotent(tmp_path: Path):
    repo = _make_repo(tmp_path)
    install(repo_root=repo)
    res = install(repo_root=repo)
    assert res.installed is False
    assert res.already_present is True
    content = _hook(repo).read_text(encoding="utf-8")
    assert _count_blocks(content) == 1


def test_install_force_replaces_existing_block_in_place(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    install(repo_root=repo)
    original = _hook(repo).read_text(encoding="utf-8")

    # Mutate the snippet so we can prove the body was replaced.
    new_snippet = (
        "# >>> comet-cc-recall (managed) >>>\n"
        "echo updated-body-marker\n"
        "# <<< comet-cc-recall (managed) <<<\n"
    )
    monkeypatch.setattr(hookmod, "_HOOK_SNIPPET", new_snippet)

    res = install(repo_root=repo, force=True)
    assert res.installed is True
    assert res.already_present is True
    new_content = _hook(repo).read_text(encoding="utf-8")
    assert "updated-body-marker" in new_content
    assert _count_blocks(new_content) == 1
    assert new_content != original


def test_install_force_on_clean_repo_acts_like_install(tmp_path: Path):
    repo = _make_repo(tmp_path)
    res = install(repo_root=repo, force=True)
    assert res.installed is True
    assert res.already_present is False
    assert _count_blocks(_hook(repo).read_text(encoding="utf-8")) == 1


def test_install_idempotent_preserves_executable_bit(tmp_path: Path):
    repo = _make_repo(tmp_path)
    install(repo_root=repo)
    # Strip executable bits and re-install: should be re-added.
    p = _hook(repo)
    p.chmod(p.stat().st_mode & ~(stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH))
    res = install(repo_root=repo)
    assert res.already_present is True
    assert res.executable is True


def test_install_uses_git_rev_parse_when_no_repo_root_given(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    monkeypatch.chdir(repo)
    res = install(runner=_ok_runner(repo))
    assert res.installed is True
    assert res.hook_path == _hook(repo)


def test_install_outside_git_repo_raises(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(HookError):
        install(runner=_bad_runner)


def test_install_when_git_missing_raises(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(HookError):
        install(runner=_missing_git_runner)


def test_install_explicit_repo_root_without_git_dir_raises(tmp_path: Path):
    bare = tmp_path / "not-a-repo"
    bare.mkdir()
    with pytest.raises(HookError):
        install(repo_root=bare)


def test_install_custom_hook_name(tmp_path: Path):
    repo = _make_repo(tmp_path)
    res = install(repo_root=repo, hook="pre-commit")
    assert res.hook_path == _hook(repo, "pre-commit")
    assert _hook(repo, "pre-commit").exists()
    assert not _hook(repo, "pre-push").exists()


# --------------------------------------------------------------------------- #
# uninstall()                                                                 #
# --------------------------------------------------------------------------- #


def test_uninstall_removes_only_managed_block(tmp_path: Path):
    repo = _make_repo(tmp_path)
    user_top = "#!/usr/bin/env bash\n# user-defined logic\necho 'pushing!'\n"
    _hook(repo).write_text(user_top, encoding="utf-8")
    install(repo_root=repo)

    res = uninstall(repo_root=repo)
    assert isinstance(res, UninstallResult)
    assert res.removed is True
    assert res.file_remains is True
    after = _hook(repo).read_text(encoding="utf-8")
    assert "# user-defined logic" in after
    assert "echo 'pushing!'" in after
    assert _count_blocks(after) == 0


def test_uninstall_when_only_block_present_keeps_file(tmp_path: Path):
    repo = _make_repo(tmp_path)
    install(repo_root=repo)
    res = uninstall(repo_root=repo)
    assert res.removed is True
    assert res.file_remains is True
    # File still exists; we never delete files we may not own outright.
    assert _hook(repo).exists()
    after = _hook(repo).read_text(encoding="utf-8")
    assert _count_blocks(after) == 0
    # Shebang preserved.
    assert after.startswith("#!/bin/sh")


def test_uninstall_when_block_absent_is_noop(tmp_path: Path):
    repo = _make_repo(tmp_path)
    user = "#!/bin/sh\necho hi\n"
    _hook(repo).write_text(user, encoding="utf-8")
    res = uninstall(repo_root=repo)
    assert res.removed is False
    assert res.file_remains is True
    assert _hook(repo).read_text(encoding="utf-8") == user


def test_uninstall_when_no_hook_file(tmp_path: Path):
    repo = _make_repo(tmp_path)
    res = uninstall(repo_root=repo)
    assert res.removed is False
    assert res.file_remains is False


def test_uninstall_outside_git_repo_raises(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(HookError):
        uninstall(runner=_bad_runner)


# --------------------------------------------------------------------------- #
# status()                                                                    #
# --------------------------------------------------------------------------- #


def test_status_no_hook_file(tmp_path: Path):
    repo = _make_repo(tmp_path)
    res = status(repo_root=repo)
    assert isinstance(res, StatusResult)
    assert res.file_exists is False
    assert res.block_present is False
    assert res.executable is False


def test_status_file_without_block(tmp_path: Path):
    repo = _make_repo(tmp_path)
    _hook(repo).write_text("#!/bin/sh\necho hi\n", encoding="utf-8")
    res = status(repo_root=repo)
    assert res.file_exists is True
    assert res.block_present is False


def test_status_file_with_block(tmp_path: Path):
    repo = _make_repo(tmp_path)
    install(repo_root=repo)
    res = status(repo_root=repo)
    assert res.file_exists is True
    assert res.block_present is True
    assert res.executable is True


def test_status_outside_git_repo_raises(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(HookError):
        status(runner=_bad_runner)


# --------------------------------------------------------------------------- #
# CLI integration                                                             #
# --------------------------------------------------------------------------- #


def _build_parser_with_hook() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd")
    add_subparser(sub)
    return p


def test_cli_hook_install_outputs_path(tmp_path: Path, monkeypatch, capsys):
    repo = _make_repo(tmp_path)
    monkeypatch.chdir(repo)
    parser = _build_parser_with_hook()
    args = parser.parse_args(["hook", "install"])
    rc = cmd_hook(args)
    out = capsys.readouterr().out
    assert rc == 0
    assert "installed managed block" in out
    assert str(_hook(repo)) in out


def test_cli_hook_install_already_present(tmp_path: Path, monkeypatch, capsys):
    repo = _make_repo(tmp_path)
    monkeypatch.chdir(repo)
    install(repo_root=repo)
    parser = _build_parser_with_hook()
    args = parser.parse_args(["hook", "install"])
    rc = cmd_hook(args)
    out = capsys.readouterr().out
    assert rc == 0
    assert "already present" in out


def test_cli_hook_install_force(tmp_path: Path, monkeypatch, capsys):
    repo = _make_repo(tmp_path)
    monkeypatch.chdir(repo)
    install(repo_root=repo)
    parser = _build_parser_with_hook()
    args = parser.parse_args(["hook", "install", "--force"])
    rc = cmd_hook(args)
    out = capsys.readouterr().out
    assert rc == 0
    assert "replaced managed block" in out


def test_cli_hook_uninstall_after_install(tmp_path: Path, monkeypatch, capsys):
    repo = _make_repo(tmp_path)
    monkeypatch.chdir(repo)
    install(repo_root=repo)
    parser = _build_parser_with_hook()
    args = parser.parse_args(["hook", "uninstall"])
    rc = cmd_hook(args)
    out = capsys.readouterr().out
    assert rc == 0
    assert "removed managed block" in out


def test_cli_hook_uninstall_no_file(tmp_path: Path, monkeypatch, capsys):
    repo = _make_repo(tmp_path)
    monkeypatch.chdir(repo)
    parser = _build_parser_with_hook()
    args = parser.parse_args(["hook", "uninstall"])
    rc = cmd_hook(args)
    out = capsys.readouterr().out
    assert rc == 0
    assert "no hook file" in out


def test_cli_hook_uninstall_no_block(tmp_path: Path, monkeypatch, capsys):
    repo = _make_repo(tmp_path)
    _hook(repo).write_text("#!/bin/sh\necho hi\n", encoding="utf-8")
    monkeypatch.chdir(repo)
    parser = _build_parser_with_hook()
    args = parser.parse_args(["hook", "uninstall"])
    rc = cmd_hook(args)
    out = capsys.readouterr().out
    assert rc == 0
    assert "no managed block" in out


def test_cli_hook_status_no_file(tmp_path: Path, monkeypatch, capsys):
    repo = _make_repo(tmp_path)
    monkeypatch.chdir(repo)
    parser = _build_parser_with_hook()
    args = parser.parse_args(["hook", "status"])
    rc = cmd_hook(args)
    out = capsys.readouterr().out
    assert rc == 0
    assert "file exists:   False" in out
    assert "block present: False" in out


def test_cli_hook_status_with_block(tmp_path: Path, monkeypatch, capsys):
    repo = _make_repo(tmp_path)
    monkeypatch.chdir(repo)
    install(repo_root=repo)
    parser = _build_parser_with_hook()
    args = parser.parse_args(["hook", "status"])
    rc = cmd_hook(args)
    out = capsys.readouterr().out
    assert rc == 0
    assert "file exists:   True" in out
    assert "block present: True" in out


def test_cli_hook_no_action_returns_1(capsys):
    parser = _build_parser_with_hook()
    args = parser.parse_args(["hook"])
    rc = cmd_hook(args)
    err = capsys.readouterr().err
    assert rc == 1
    assert "usage" in err.lower()


def test_cli_hook_outside_git_repo_returns_1(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    parser = _build_parser_with_hook()
    args = parser.parse_args(["hook", "status"])
    rc = cmd_hook(args)
    err = capsys.readouterr().err
    assert rc == 1
    assert "not a git repository" in err


def test_cli_hook_custom_hook_name(tmp_path: Path, monkeypatch, capsys):
    repo = _make_repo(tmp_path)
    monkeypatch.chdir(repo)
    parser = _build_parser_with_hook()
    args = parser.parse_args(["hook", "install", "--hook", "pre-commit"])
    rc = cmd_hook(args)
    out = capsys.readouterr().out
    assert rc == 0
    assert "pre-commit" in out
    assert _hook(repo, "pre-commit").exists()


# --------------------------------------------------------------------------- #
# Snippet correctness                                                         #
# --------------------------------------------------------------------------- #


def test_snippet_is_non_blocking(tmp_path: Path):
    repo = _make_repo(tmp_path)
    install(repo_root=repo)
    content = _hook(repo).read_text(encoding="utf-8")
    # The hook must not abort the push under any of its own code paths.
    assert "exit 1" not in content
    # Stderr-only output (so stdout stays clean for the push pipe).
    assert ">&2" in content
    # Failure-tolerant: the recall command's nonzero exit must not propagate.
    assert "|| true" in content
