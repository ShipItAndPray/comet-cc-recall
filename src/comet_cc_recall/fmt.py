"""Terminal output formatting. Plain text + ANSI colors when stdout is a TTY."""

from __future__ import annotations

import sys
from collections.abc import Iterable
from datetime import datetime, timezone

from comet_cc_recall.recall import RecallHit


def _supports_color(stream=sys.stdout) -> bool:
    return hasattr(stream, "isatty") and stream.isatty()


def _c(text: str, code: str, *, on: bool) -> str:
    return f"\x1b[{code}m{text}\x1b[0m" if on else text


def format_hits(hits: Iterable[RecallHit], *, color: bool | None = None) -> str:
    """Pretty-print hits as a multi-line block."""
    on = _supports_color() if color is None else color
    lines: list[str] = []
    items = list(hits)
    if not items:
        return _c("no recalled nodes", "2", on=on)
    width = max(len(h.node_id) for h in items)
    for h in items:
        when = ""
        if h.created_at:
            when = datetime.fromtimestamp(h.created_at, tz=timezone.utc).strftime("%Y-%m-%d")
        head = " ".join(
            x
            for x in (
                _c(h.node_id.ljust(width), "36", on=on),
                _c(f"{h.score:.2f}", "33", on=on),
                _c(h.importance, "35", on=on),
                _c(when, "2", on=on) if when else "",
            )
            if x
        )
        lines.append(head)
        if h.summary:
            lines.append("  " + h.summary)
        if h.trigger:
            lines.append("  " + _c("trigger:", "2", on=on) + " " + h.trigger)
        if h.tags:
            lines.append("  " + _c("tags:", "2", on=on) + " " + ", ".join(h.tags))
        lines.append("")
    # Trim trailing blank
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines)


def format_node_read(payload: dict, *, color: bool | None = None) -> str:
    """Format a `read_memory` response payload at any depth."""
    on = _supports_color() if color is None else color
    lines: list[str] = []
    nid = payload.get("node_id") or ""
    if nid:
        lines.append(_c(nid, "36", on=on))
    summary = payload.get("summary")
    if summary:
        lines.append(_c("summary:", "1", on=on))
        lines.append(summary)
    detailed = payload.get("detailed_summary")
    if detailed:
        lines.append("")
        lines.append(_c("detailed:", "1", on=on))
        lines.append(detailed)
    raw_turns = payload.get("raw_turns")
    if raw_turns:
        lines.append("")
        lines.append(_c("raw turns:", "1", on=on))
        for t in raw_turns:
            role = t.get("role", "?")
            text = t.get("text", "")
            lines.append(_c(f"[{role}]", "2", on=on) + " " + text)
    return "\n".join(lines)
