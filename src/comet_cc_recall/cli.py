"""`comet-cc-recall` CLI entrypoint."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from comet_cc_recall import __version__
from comet_cc_recall.client import DaemonClient, DaemonError
from comet_cc_recall.context import DEFAULT_INSTRUCTION, context_block
from comet_cc_recall.diff import diff_recall
from comet_cc_recall.filters import filter_hits, parse_since
from comet_cc_recall.fmt import format_hits_any, format_node_read
from comet_cc_recall.recall import recall
from comet_cc_recall.related import related
from comet_cc_recall.search import search

OUTPUT_CHOICES = ("text", "json", "md", "llm")


def _add_filter_flags(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--tag",
        action="append",
        default=[],
        help="Only return nodes carrying this tag. Repeat for OR-match.",
    )
    p.add_argument(
        "--importance",
        action="append",
        default=[],
        choices=["HIGH", "MED", "LOW"],
        help="Restrict to one or more importance levels. Repeat for OR-match.",
    )
    p.add_argument(
        "--since",
        type=str,
        default=None,
        help="Only nodes newer than this (e.g. `30d`, `12h`, `2026-04-01`).",
    )


def _add_output_flags(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "-o",
        "--output",
        choices=OUTPUT_CHOICES,
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


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="comet-cc-recall",
        description="File-anchored memory recall for CoMeT-CC.",
    )
    p.add_argument("--version", action="version", version=f"comet-cc-recall {__version__}")
    sub = p.add_subparsers(dest="cmd")

    rec = sub.add_parser("recall", help="Recall memory nodes anchored to a file (default).")
    rec.add_argument("path", type=str, help="Path to a source file.")
    rec.add_argument("-k", "--top-k", type=int, default=5)
    rec.add_argument("--min-score", type=float, default=0.20)
    rec.add_argument("--no-repo-filter", action="store_true")
    _add_filter_flags(rec)
    _add_output_flags(rec)

    srch = sub.add_parser("search", help="Raw semantic search by free-text query.")
    srch.add_argument("query", type=str, help="Natural-language query string.")
    srch.add_argument("-k", "--top-k", type=int, default=5)
    srch.add_argument("--min-score", type=float, default=0.20)
    _add_filter_flags(srch)
    _add_output_flags(srch)

    rel = sub.add_parser("related", help="Walk the node graph from a seed node id.")
    rel.add_argument("node_id", type=str)
    rel.add_argument("--depth", type=int, default=1, choices=[1, 2])
    rel.add_argument("-k", "--top-k", type=int, default=8)
    _add_filter_flags(rel)
    _add_output_flags(rel)

    df = sub.add_parser("diff", help="Recall against the union of `git diff` files.")
    df.add_argument("base", nargs="?", default=None, help="Optional base ref (e.g. `main`, `HEAD~3`).")
    df.add_argument("-k", "--top-k", type=int, default=5)
    _add_filter_flags(df)
    _add_output_flags(df)

    ctx = sub.add_parser(
        "context",
        help="Emit a <recalled-memory> block for pasting into a fresh agent prompt.",
    )
    ctx.add_argument("path", type=str)
    ctx.add_argument("-k", "--top-k", type=int, default=5)
    ctx.add_argument("--min-score", type=float, default=0.20)
    ctx.add_argument("--instruction", type=str, default=DEFAULT_INSTRUCTION)

    read = sub.add_parser("read", help="Read a recalled node at depth 0/1/2.")
    read.add_argument("node_id")
    read.add_argument("--depth", type=int, default=0, choices=[0, 1, 2])
    read.add_argument("--json", action="store_true")
    read.add_argument("--color", choices=["auto", "always", "never"], default="auto")

    sub.add_parser("doctor", help="Check daemon reachability + emit diagnostics.")
    return p


_KNOWN_SUBCOMMANDS = {"recall", "search", "related", "diff", "context", "read", "doctor"}


def _desugar_bare_path(argv: Sequence[str]) -> list[str]:
    """`comet-cc-recall <path>` → `comet-cc-recall recall <path>`."""
    args = list(argv)
    if not args:
        return args
    first = args[0]
    if first.startswith("-") or first in _KNOWN_SUBCOMMANDS:
        return args
    return ["recall", *args]


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


def _apply_filters(hits, args: argparse.Namespace):
    since = None
    if getattr(args, "since", None):
        try:
            since = parse_since(args.since)
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr)
            raise SystemExit(2) from None
    return filter_hits(
        hits,
        tags=getattr(args, "tag", None) or None,
        importance=getattr(args, "importance", None) or None,
        since=since,
    )


def _emit_hits(hits, args: argparse.Namespace, *, anchor: str | None = None,
               instruction: str | None = None, heading: str | None = None) -> None:
    fmt = _resolve_output(args)
    out = format_hits_any(
        hits,
        fmt=fmt,
        color=_resolve_color(getattr(args, "color", "auto")),
        anchor=anchor,
        instruction=instruction,
        heading=heading,
    )
    print(out)


def _cmd_recall(args, *, client: DaemonClient | None = None) -> int:
    p = Path(args.path)
    if not p.exists():
        print(f"error: file not found: {args.path}", file=sys.stderr)
        return 2
    try:
        hits = recall(
            p,
            client=client,
            top_k=args.top_k,
            min_score=args.min_score,
            repo_filter=not args.no_repo_filter,
        )
    except DaemonError as e:
        print(f"error: {e}", file=sys.stderr)
        print("hint: is the comet-cc daemon running? `comet-cc daemon start`", file=sys.stderr)
        return 3
    hits = _apply_filters(hits, args)
    _emit_hits(hits, args, heading=f"recall: {args.path}")
    return 0


def _cmd_search(args, *, client: DaemonClient | None = None) -> int:
    try:
        hits = search(args.query, client=client, top_k=args.top_k, min_score=args.min_score)
    except DaemonError as e:
        print(f"error: {e}", file=sys.stderr)
        return 3
    hits = _apply_filters(hits, args)
    _emit_hits(hits, args, heading=f"search: {args.query!r}")
    return 0


def _cmd_related(args, *, client: DaemonClient | None = None) -> int:
    try:
        hits = related(args.node_id, client=client, depth=args.depth, top_k=args.top_k)
    except DaemonError as e:
        print(f"error: {e}", file=sys.stderr)
        return 3
    hits = _apply_filters(hits, args)
    _emit_hits(hits, args, heading=f"related to {args.node_id} (depth {args.depth})")
    return 0


def _cmd_diff(args, *, client: DaemonClient | None = None) -> int:
    try:
        hits = diff_recall(args.base, client=client, top_k=args.top_k)
    except DaemonError as e:
        print(f"error: {e}", file=sys.stderr)
        return 3
    hits = _apply_filters(hits, args)
    label = f"diff (base={args.base})" if args.base else "diff (working tree)"
    _emit_hits(hits, args, heading=label)
    return 0


def _cmd_context(args, *, client: DaemonClient | None = None) -> int:
    p = Path(args.path)
    if not p.exists():
        print(f"error: file not found: {args.path}", file=sys.stderr)
        return 2
    try:
        block = context_block(
            p,
            client=client,
            top_k=args.top_k,
            min_score=args.min_score,
            instruction=args.instruction,
        )
    except DaemonError as e:
        print(f"error: {e}", file=sys.stderr)
        return 3
    if not block:
        print("<recalled-memory><empty/></recalled-memory>")
    else:
        print(block)
    return 0


def _cmd_read(args, *, client: DaemonClient | None = None) -> int:
    cli = client or DaemonClient.default()
    try:
        payload = cli.read_memory(args.node_id, depth=args.depth)
    except DaemonError as e:
        print(f"error: {e}", file=sys.stderr)
        return 3
    if args.json:
        import json as _json
        print(_json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(format_node_read(payload, color=_resolve_color(args.color)))
    return 0


def _cmd_doctor(_args, *, client: DaemonClient | None = None) -> int:
    cli = client or DaemonClient.default()
    sock = cli.socket_path
    print(f"socket: {sock}")
    print(f"socket exists: {sock.exists()}")
    print(f"daemon ping: {cli.is_running()}")
    return 0 if cli.is_running() else 1


def main(argv: Sequence[str] | None = None, *, client: DaemonClient | None = None) -> int:
    parser = _build_parser()
    raw = list(argv) if argv is not None else sys.argv[1:]
    if not raw:
        parser.print_help()
        return 0
    args = parser.parse_args(_desugar_bare_path(raw))

    handlers = {
        "recall": _cmd_recall,
        "search": _cmd_search,
        "related": _cmd_related,
        "diff": _cmd_diff,
        "context": _cmd_context,
        "read": _cmd_read,
        "doctor": _cmd_doctor,
    }
    if args.cmd in handlers:
        try:
            return handlers[args.cmd](args, client=client)
        except SystemExit as e:
            return int(e.code) if isinstance(e.code, int) else 1
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
