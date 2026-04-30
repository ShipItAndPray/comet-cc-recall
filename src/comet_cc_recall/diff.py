"""Diff-aware recall — `comet-cc-recall diff [base]`.

Asks git for the set of changed files between `HEAD` and a base ref
(default `HEAD~1` if available, else the working tree), then runs the
file-anchored recall pipeline against each one and merges results.

The merge keeps the highest-scoring instance of any node and dedupes by
`node_id`.
"""

from __future__ import annotations

import subprocess
from collections.abc import Iterable
from pathlib import Path

from comet_cc_recall.client import DaemonClient
from comet_cc_recall.recall import DEFAULT_TOP_K, RecallHit, recall
from comet_cc_recall.symbols import detect_language


def changed_files(
    base: str | None = None,
    *,
    cwd: str | Path | None = None,
    runner=subprocess.run,  # injectable for tests
) -> list[Path]:
    """Files modified between `base` and the working tree.

    Resolution order:
      - `base` provided → `git diff --name-only <base>`
      - else → `git diff --name-only HEAD` (staged + unstaged vs HEAD)
        plus `git ls-files --others --exclude-standard` for untracked.
    Lines that come back empty are skipped. Output is repo-relative; we
    join against the repo root so callers receive absolute paths.
    """
    cwd_path = Path(cwd) if cwd is not None else Path.cwd()
    repo_root = _git_toplevel(cwd_path, runner)
    if repo_root is None:
        return []

    files: list[str] = []
    if base:
        files += _git_lines(["git", "diff", "--name-only", base], repo_root, runner)
    else:
        files += _git_lines(["git", "diff", "--name-only", "HEAD"], repo_root, runner)
        files += _git_lines(
            ["git", "ls-files", "--others", "--exclude-standard"], repo_root, runner
        )

    seen: set[str] = set()
    out: list[Path] = []
    for f in files:
        if not f or f in seen:
            continue
        seen.add(f)
        p = repo_root / f
        if p.is_file():
            out.append(p)
    return out


def _git_toplevel(cwd: Path, runner) -> Path | None:
    try:
        r = runner(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return None
    if r.returncode != 0:
        return None
    line = (r.stdout or "").strip()
    return Path(line) if line else None


def _git_lines(cmd: list[str], cwd: Path, runner) -> list[str]:
    try:
        r = runner(cmd, cwd=str(cwd), capture_output=True, text=True, check=False)
    except FileNotFoundError:
        return []
    if r.returncode != 0:
        return []
    return [ln.strip() for ln in (r.stdout or "").splitlines() if ln.strip()]


def diff_recall(
    base: str | None = None,
    *,
    client: DaemonClient | None = None,
    top_k: int = DEFAULT_TOP_K,
    cwd: str | Path | None = None,
    runner=subprocess.run,
    paths: Iterable[Path] | None = None,
) -> list[RecallHit]:
    """Recall against the union of changed files. Skips files of unsupported
    languages. Results are merged by node_id keeping the max score."""
    files = list(paths) if paths is not None else changed_files(base, cwd=cwd, runner=runner)
    files = [f for f in files if detect_language(f) is not None]

    by_id: dict[str, RecallHit] = {}
    for f in files:
        try:
            hits = recall(f, client=client, top_k=top_k)
        except Exception:  # pragma: no cover
            continue
        for h in hits:
            existing = by_id.get(h.node_id)
            if existing is None or h.score > existing.score:
                by_id[h.node_id] = h

    merged = sorted(by_id.values(), key=lambda h: h.score, reverse=True)
    return merged[:top_k]
