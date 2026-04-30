"""Git pre-push hook installer for comet-cc-recall.

Manages a small, sentinel-delimited block inside `.git/hooks/<hook>` that
calls `comet-cc-recall diff -o text` and prints the recalled-memory block
to stderr. The hook is informational only and never blocks the push.
"""

from __future__ import annotations

import re
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path

_BEGIN_SENTINEL = "# >>> comet-cc-recall (managed) >>>"
_END_SENTINEL = "# <<< comet-cc-recall (managed) <<<"

_HOOK_SNIPPET = """\
# >>> comet-cc-recall (managed) >>>
# Surfaces recalled memory nodes for files in this push. Non-blocking.
if command -v comet-cc-recall >/dev/null 2>&1; then
    BLOCK=$(comet-cc-recall diff -o text --color never 2>/dev/null || true)
    if [ -n "$BLOCK" ]; then
        printf '\\n--- comet-cc-recall: prior memory for changed files ---\\n%s\\n\\n' "$BLOCK" >&2
    fi
fi
# <<< comet-cc-recall (managed) <<<
"""

_DEFAULT_SHEBANG = "#!/bin/sh\n"

_BLOCK_RE = re.compile(
    re.escape(_BEGIN_SENTINEL) + r".*?" + re.escape(_END_SENTINEL) + r"\n?",
    re.DOTALL,
)


@dataclass(frozen=True)
class InstallResult:
    hook_path: Path
    installed: bool
    already_present: bool
    executable: bool


@dataclass(frozen=True)
class UninstallResult:
    hook_path: Path
    removed: bool
    file_remains: bool


@dataclass(frozen=True)
class StatusResult:
    hook_path: Path
    file_exists: bool
    block_present: bool
    executable: bool


class HookError(RuntimeError):
    """Raised when hook operations cannot proceed (e.g. not a git repo)."""


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


def _walk_to_git_dir(start: Path) -> Path | None:
    cur = start.resolve()
    for candidate in [cur, *cur.parents]:
        if (candidate / ".git").exists():
            return candidate
    return None


def _resolve_repo_root(repo_root: Path | None, runner) -> Path:
    if repo_root is not None:
        root = Path(repo_root)
        if not (root / ".git").exists():
            raise HookError(f"not a git repository: {root}")
        return root
    cwd = Path.cwd()
    root = _git_toplevel(cwd, runner)
    if root is None:
        # Fallback: if `git` is unavailable or returned nonzero, walk up
        # for a `.git` marker. Lets the installer work in environments
        # without git on PATH (e.g. minimal CI images).
        root = _walk_to_git_dir(cwd)
    if root is None:
        raise HookError(f"not a git repository: {cwd}")
    return root


def _hook_path(repo_root: Path, hook: str) -> Path:
    git_dir = repo_root / ".git"
    return git_dir / "hooks" / hook


def _is_executable(path: Path) -> bool:
    try:
        mode = path.stat().st_mode
    except FileNotFoundError:
        return False
    return bool(mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH))


def _make_executable(path: Path) -> None:
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _block_present(content: str) -> bool:
    return _BLOCK_RE.search(content) is not None


def install(
    repo_root: Path | None = None,
    *,
    hook: str = "pre-push",
    force: bool = False,
    runner=subprocess.run,
) -> InstallResult:
    """Write the managed block into `.git/hooks/<hook>`.

    Creates the hook file with a `#!/bin/sh` shebang if it doesn't exist.
    If our managed block is already present, leaves it alone unless
    `force=True`, in which case the existing block is replaced in place.
    """
    root = _resolve_repo_root(repo_root, runner)
    hook_path = _hook_path(root, hook)
    hook_path.parent.mkdir(parents=True, exist_ok=True)

    if not hook_path.exists():
        content = _DEFAULT_SHEBANG + "\n" + _HOOK_SNIPPET
        hook_path.write_text(content, encoding="utf-8")
        _make_executable(hook_path)
        return InstallResult(
            hook_path=hook_path,
            installed=True,
            already_present=False,
            executable=_is_executable(hook_path),
        )

    existing = hook_path.read_text(encoding="utf-8")
    already = _block_present(existing)

    if already and not force:
        if not _is_executable(hook_path):
            _make_executable(hook_path)
        return InstallResult(
            hook_path=hook_path,
            installed=False,
            already_present=True,
            executable=_is_executable(hook_path),
        )

    if already and force:
        new_content = _BLOCK_RE.sub(_HOOK_SNIPPET, existing, count=1)
    else:
        if existing and not existing.endswith("\n"):
            existing += "\n"
        new_content = existing + "\n" + _HOOK_SNIPPET

    hook_path.write_text(new_content, encoding="utf-8")
    if not _is_executable(hook_path):
        _make_executable(hook_path)
    return InstallResult(
        hook_path=hook_path,
        installed=True,
        already_present=already,
        executable=_is_executable(hook_path),
    )


def uninstall(
    repo_root: Path | None = None,
    *,
    hook: str = "pre-push",
    runner=subprocess.run,
) -> UninstallResult:
    """Remove only the managed block. Preserves any other content."""
    root = _resolve_repo_root(repo_root, runner)
    hook_path = _hook_path(root, hook)
    if not hook_path.exists():
        return UninstallResult(hook_path=hook_path, removed=False, file_remains=False)

    existing = hook_path.read_text(encoding="utf-8")
    if not _block_present(existing):
        return UninstallResult(hook_path=hook_path, removed=False, file_remains=True)

    new_content = _BLOCK_RE.sub("", existing, count=1)
    new_content = re.sub(r"\n{3,}", "\n\n", new_content)
    hook_path.write_text(new_content, encoding="utf-8")
    return UninstallResult(hook_path=hook_path, removed=True, file_remains=True)


def status(
    repo_root: Path | None = None,
    *,
    hook: str = "pre-push",
    runner=subprocess.run,
) -> StatusResult:
    """Report whether the hook file and our managed block are present."""
    root = _resolve_repo_root(repo_root, runner)
    hook_path = _hook_path(root, hook)
    if not hook_path.exists():
        return StatusResult(
            hook_path=hook_path,
            file_exists=False,
            block_present=False,
            executable=False,
        )
    content = hook_path.read_text(encoding="utf-8")
    return StatusResult(
        hook_path=hook_path,
        file_exists=True,
        block_present=_block_present(content),
        executable=_is_executable(hook_path),
    )


__all__ = [
    "HookError",
    "InstallResult",
    "StatusResult",
    "UninstallResult",
    "install",
    "status",
    "uninstall",
]
