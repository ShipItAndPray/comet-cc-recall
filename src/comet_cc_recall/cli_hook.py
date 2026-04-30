"""CLI surface for the `hook` subcommand: install/uninstall/status."""

from __future__ import annotations

import argparse
import sys
from typing import Any

from comet_cc_recall.hook import HookError, install, status, uninstall


def add_subparser(subparsers: Any) -> argparse.ArgumentParser:
    """Attach the `hook` subparser (and its three sub-subcommands)."""
    hook = subparsers.add_parser(
        "hook",
        help="Manage the comet-cc-recall git pre-push hook.",
    )
    hook_sub = hook.add_subparsers(dest="hook_action")

    inst = hook_sub.add_parser("install", help="Install the managed hook block.")
    inst.add_argument("--hook", default="pre-push", help="Hook name (default: pre-push).")
    inst.add_argument(
        "--force",
        action="store_true",
        help="Replace an existing managed block in place.",
    )

    uninst = hook_sub.add_parser("uninstall", help="Remove the managed hook block.")
    uninst.add_argument("--hook", default="pre-push", help="Hook name (default: pre-push).")

    stat_p = hook_sub.add_parser("status", help="Report installation status.")
    stat_p.add_argument("--hook", default="pre-push", help="Hook name (default: pre-push).")

    return hook


def cmd_hook(args: argparse.Namespace, *, client: Any = None) -> int:
    """Dispatch a parsed `hook` subcommand. Returns 0 on success, 1 on failure."""
    del client  # not used; signature mirrors other CLI handlers
    action = getattr(args, "hook_action", None)
    hook_name = getattr(args, "hook", "pre-push")

    if action is None:
        print(
            "usage: comet-cc-recall hook {install,uninstall,status} [--hook NAME]",
            file=sys.stderr,
        )
        return 1

    try:
        if action == "install":
            return _do_install(hook_name, force=getattr(args, "force", False))
        if action == "uninstall":
            return _do_uninstall(hook_name)
        if action == "status":
            return _do_status(hook_name)
    except HookError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    print(f"error: unknown hook action: {action}", file=sys.stderr)
    return 1


def _do_install(hook_name: str, *, force: bool) -> int:
    res = install(hook=hook_name, force=force)
    if res.installed and res.already_present and force:
        print(f"replaced managed block in {res.hook_path}")
    elif res.installed:
        print(f"installed managed block in {res.hook_path}")
    elif res.already_present:
        print(f"managed block already present in {res.hook_path} (use --force to replace)")
    else:  # pragma: no cover - defensive
        print(f"no change: {res.hook_path}")
    if not res.executable:
        print(f"warning: {res.hook_path} is not executable", file=sys.stderr)
    return 0


def _do_uninstall(hook_name: str) -> int:
    res = uninstall(hook=hook_name)
    if res.removed:
        print(f"removed managed block from {res.hook_path}")
    elif not res.file_remains:
        print(f"no hook file at {res.hook_path}; nothing to do")
    else:
        print(f"no managed block in {res.hook_path}; nothing to do")
    return 0


def _do_status(hook_name: str) -> int:
    res = status(hook=hook_name)
    print(f"hook path:     {res.hook_path}")
    print(f"file exists:   {res.file_exists}")
    print(f"block present: {res.block_present}")
    print(f"executable:    {res.executable}")
    return 0


__all__ = ["add_subparser", "cmd_hook"]
