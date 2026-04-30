from __future__ import annotations

from pathlib import Path

from comet_cc_recall.repo import (
    find_repo_root,
    relative_path,
    repo_match_score,
    repo_name,
)


def test_find_repo_root_walks_up(fake_repo: Path):
    nested = fake_repo / "src" / "deep"
    nested.mkdir(parents=True)
    f = nested / "x.py"
    f.write_text("")
    assert find_repo_root(f) == fake_repo


def test_find_repo_root_none_when_no_git(tmp_path: Path):
    f = tmp_path / "loose.py"
    f.write_text("")
    assert find_repo_root(f) is None


def test_relative_path_inside_repo(fake_repo: Path):
    f = fake_repo / "src" / "x.py"
    f.parent.mkdir()
    f.write_text("")
    assert relative_path(f, fake_repo) == "src/x.py"


def test_relative_path_outside_repo_falls_back_to_basename(tmp_path: Path):
    f = tmp_path / "loose.py"
    f.write_text("")
    assert relative_path(f, None) == "loose.py"


def test_repo_name_uses_root_dir_name(fake_repo: Path):
    assert repo_name(fake_repo) == "myrepo"


def test_repo_name_falls_back_to_parent(tmp_path: Path):
    f = tmp_path / "scratch" / "x.py"
    f.parent.mkdir()
    f.write_text("")
    assert repo_name(None, fallback=f) == "scratch"


def test_match_score_file_path_full():
    bonus = repo_match_score("we debugged services/payments.py at length", repo="myapp", file_rel="services/payments.py")
    assert bonus >= 0.25


def test_match_score_file_basename_only():
    bonus = repo_match_score("payments.py is gnarly", repo="myapp", file_rel="services/payments.py")
    assert 0.10 <= bonus <= 0.20


def test_match_score_repo_only():
    bonus = repo_match_score("touched the myapp repo today", repo="myapp", file_rel="other.py")
    assert 0.0 < bonus <= 0.1


def test_match_score_no_match_zero():
    assert repo_match_score("totally unrelated content", repo="myapp", file_rel="x.py") == 0.0


def test_match_score_capped():
    """File + basename + repo all match → still bounded at 0.4."""
    text = "myrepo myrepo services/payments.py services/payments.py payments.py myrepo"
    bonus = repo_match_score(text, repo="myrepo", file_rel="services/payments.py")
    assert bonus <= 0.4
