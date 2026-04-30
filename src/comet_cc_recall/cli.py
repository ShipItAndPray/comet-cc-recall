"""`comet-cc-recall` CLI entrypoint."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from comet_cc_recall import __version__
from comet_cc_recall.client import DaemonClient, DaemonError
from comet_cc_recall.fmt import format_hits, format_node_read
from comet_cc_recall.recall import recall


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="comet-cc-recall",
        description="File-anchored memory recall for CoMeT-CC.",
    )
    p.add_argument("--version", action="version", version=f"comet-cc-recall {__version__}")
    sub = p.add_subparsers(dest="cmd")

    rec = sub.add_parser(
        "recall",
        help="Recall memory nodes anchored to a file (default).",
    )
    rec.add_argument("path", type=str, help="Path to a source file.")
    rec.add_argument("-k", "--top-k", type=int, default=5, help="Max hits (default 5).")
    rec.add_argument("--min-score", type=float, default=0.20, help="Cosine floor (default 0.20).")
    rec.add_argument("--no-repo-filter", action="store_true", help="Disable repo bonus rerank.")
    rec.add_argument("--json", action="store_true", help="Emit JSON instead of pretty text.")
    rec.add_argument("--color", choices=["auto", "always", "never"], default="auto")

    read = sub.add_parser("read", help="Read a recalled node at depth 0/1/2.")
    read.add_argument("node_id")
    read.add_argument("--depth", type=int, default=0, choices=[0, 1, 2])
    read.add_argument("--json", action="store_true")
    read.add_argument("--color", choices=["auto", "always", "never"], default="auto")

    sub.add_parser("doctor", help="Check daemon reachability + emit diagnostics.")
    return p


_KNOWN_SUBCOMMANDS = {"recall", "read", "doctor"}


def _desugar_bare_path(argv: Sequence[str]) -> list[str]:
    """`comet-cc-recall <path>` → `comet-cc-recall recall <path>`.

    Triggered only when the first token isn't a known subcommand or a
    flag. Keeps argparse simple and avoids a positional argument at the
    top level (which conflicts with `add_subparsers`)."""
    args = list(argv)
    if not args:
        return args
    first = args[0]
    if first.startswith("-"):
        return args
    if first in _KNOWN_SUBCOMMANDS:
        return args
    return ["recall", *args]


def _resolve_color(flag: str) -> bool | None:
    if flag == "always":
        return True
    if flag == "never":
        return False
    return None


def _cmd_recall(args: argparse.Namespace, *, client: DaemonClient | None = None) -> int:
    path = Path(args.path)
    if not path.exists():
        print(f"error: file not found: {args.path}", file=sys.stderr)
        return 2
    try:
        hits = recall(
            path,
            client=client,
            top_k=args.top_k,
            min_score=args.min_score,
            repo_filter=not args.no_repo_filter,
        )
    except DaemonError as e:
        print(f"error: {e}", file=sys.stderr)
        print("hint: is the comet-cc daemon running? `comet-cc daemon start`", file=sys.stderr)
        return 3

    if args.json:
        payload = [
            {
                "node_id": h.node_id,
                "score": round(h.score, 4),
                "summary": h.summary,
                "trigger": h.trigger,
                "importance": h.importance,
                "tags": list(h.tags),
                "session_id": h.session_id,
                "created_at": h.created_at,
            }
            for h in hits
        ]
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(format_hits(hits, color=_resolve_color(args.color)))
    return 0


def _cmd_read(args: argparse.Namespace, *, client: DaemonClient | None = None) -> int:
    cli = client or DaemonClient.default()
    try:
        payload = cli.read_memory(args.node_id, depth=args.depth)
    except DaemonError as e:
        print(f"error: {e}", file=sys.stderr)
        return 3
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(format_node_read(payload, color=_resolve_color(args.color)))
    return 0


def _cmd_doctor(_args: argparse.Namespace, *, client: DaemonClient | None = None) -> int:
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

    if args.cmd is None:
        parser.print_help()
        return 0
    if args.cmd == "recall":
        return _cmd_recall(args, client=client)
    if args.cmd == "read":
        return _cmd_read(args, client=client)
    if args.cmd == "doctor":
        return _cmd_doctor(args, client=client)
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
