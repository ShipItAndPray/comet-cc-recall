"""`comet-cc-recall digest` subparser + handler.

Wired into the main CLI by `cli.py`. Lives in its own module so the
digest feature can ship without touching the existing CLI surface."""

from __future__ import annotations

import argparse
import sys

from comet_cc_recall.client import DaemonClient, DaemonError
from comet_cc_recall.digest import (
    DEFAULT_SINCE,
    DEFAULT_TOP_PER_TAG,
    DEFAULT_UNTAGGED_LABEL,
    digest,
    format_digest_any,
)
from comet_cc_recall.filters import parse_since

DIGEST_OUTPUT_CHOICES = ("text", "json", "md")


def add_subparser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    """Register the `digest` subparser. Returns the parser for tests."""
    p = subparsers.add_parser(
        "digest",
        help="Periodic tag-grouped digest of recent memory nodes.",
    )
    p.add_argument(
        "--since",
        type=str,
        default=DEFAULT_SINCE,
        help="Window start (e.g. `7d`, `12h`, `2026-04-01`). Default: 7d.",
    )
    p.add_argument(
        "--importance",
        action="append",
        default=[],
        choices=["HIGH", "MED", "LOW"],
        help="Restrict to one or more importance levels. Repeat for OR-match.",
    )
    p.add_argument(
        "--top-per-tag",
        type=int,
        default=DEFAULT_TOP_PER_TAG,
        help=f"How many hits to surface per tag group. Default: {DEFAULT_TOP_PER_TAG}.",
    )
    p.add_argument(
        "--max-groups",
        type=int,
        default=None,
        help="Cap the number of tag groups returned.",
    )
    p.add_argument(
        "--untagged-label",
        type=str,
        default=DEFAULT_UNTAGGED_LABEL,
        help="Bucket label for nodes with no tags.",
    )
    p.add_argument(
        "-o",
        "--output",
        choices=DIGEST_OUTPUT_CHOICES,
        default="text",
        help="Output format (default: text).",
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="Shorthand for --output json.",
    )
    p.add_argument(
        "--color",
        choices=["auto", "always", "never"],
        default="auto",
        help="ANSI color in text output.",
    )
    return p


def _resolve_color(flag: str) -> bool | None:
    if flag == "always":
        return True
    if flag == "never":
        return False
    return None


def _resolve_output(args: argparse.Namespace) -> str:
    if getattr(args, "json", False):
        return "json"
    return getattr(args, "output", "text")


def cmd_digest(args: argparse.Namespace, *, client: DaemonClient | None = None) -> int:
    """Handle `comet-cc-recall digest ...`. Returns process exit code."""
    since_value = getattr(args, "since", DEFAULT_SINCE)
    try:
        parse_since(since_value)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    importance = list(getattr(args, "importance", []) or []) or None

    try:
        d = digest(
            since=since_value,
            importance=importance,
            top_per_tag=getattr(args, "top_per_tag", DEFAULT_TOP_PER_TAG),
            max_groups=getattr(args, "max_groups", None),
            untagged_label=getattr(args, "untagged_label", DEFAULT_UNTAGGED_LABEL),
            client=client,
        )
    except DaemonError as e:
        print(f"error: {e}", file=sys.stderr)
        print(
            "hint: is the comet-cc daemon running? `comet-cc daemon start`",
            file=sys.stderr,
        )
        return 3

    fmt = _resolve_output(args)
    out = format_digest_any(d, fmt=fmt, color=_resolve_color(getattr(args, "color", "auto")))
    print(out)
    return 0
