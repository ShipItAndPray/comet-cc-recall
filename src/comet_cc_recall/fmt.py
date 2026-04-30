"""Output formatting in three flavors:

- text: ANSI-colored or plain (default)
- markdown: clean cards for pasting into docs
- llm: a `<recalled-memory>` block intended to be pasted into a fresh
  agent prompt (mirrors the upstream daemon's system-reminder shape)
"""

from __future__ import annotations

import json
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


def _isodate(ts: float) -> str:
    if not ts:
        return ""
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")


def format_hits_markdown(hits: Iterable[RecallHit], *, heading: str | None = None) -> str:
    """One markdown card per hit. Stable, paste-friendly."""
    items = list(hits)
    out: list[str] = []
    if heading:
        out.append(f"# {heading}\n")
    if not items:
        out.append("_no recalled nodes_")
        return "\n".join(out)
    for h in items:
        when = _isodate(h.created_at)
        meta = " · ".join(x for x in (h.importance, when, f"score {h.score:.2f}") if x)
        out.append(f"## `{h.node_id}`")
        out.append(f"_{meta}_\n")
        if h.summary:
            out.append(h.summary + "\n")
        if h.trigger:
            out.append(f"**trigger:** {h.trigger}\n")
        if h.tags:
            out.append("**tags:** " + ", ".join(f"`{t}`" for t in h.tags) + "\n")
    return "\n".join(out).rstrip() + "\n"


def format_hits_llm(
    hits: Iterable[RecallHit],
    *,
    anchor: str | None = None,
    instruction: str | None = None,
) -> str:
    """A `<recalled-memory>` system-reminder-shaped block intended to be
    pasted at the top of a fresh Claude/agent prompt."""
    items = list(hits)
    lines: list[str] = ["<recalled-memory>"]
    if anchor:
        lines.append(f"  <anchor>{anchor}</anchor>")
    if instruction:
        lines.append(f"  <instruction>{instruction}</instruction>")
    if not items:
        lines.append("  <empty/>")
    for h in items:
        attrs = [
            f'id="{h.node_id}"',
            f'importance="{h.importance}"',
            f'score="{h.score:.2f}"',
        ]
        if h.created_at:
            attrs.append(f'date="{_isodate(h.created_at)}"')
        if h.tags:
            attrs.append(f'tags="{",".join(h.tags)}"')
        lines.append(f"  <node {' '.join(attrs)}>")
        if h.summary:
            lines.append(f"    <summary>{h.summary}</summary>")
        if h.trigger:
            lines.append(f"    <trigger>{h.trigger}</trigger>")
        lines.append("  </node>")
    lines.append("</recalled-memory>")
    return "\n".join(lines)


def format_hits_json(hits: Iterable[RecallHit]) -> str:
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
    return json.dumps(payload, ensure_ascii=False, indent=2)


def format_hits_any(
    hits: Iterable[RecallHit],
    *,
    fmt: str,
    color: bool | None = None,
    anchor: str | None = None,
    instruction: str | None = None,
    heading: str | None = None,
) -> str:
    """Dispatch: text / json / md / llm."""
    items = list(hits)
    if fmt == "json":
        return format_hits_json(items)
    if fmt == "md":
        return format_hits_markdown(items, heading=heading)
    if fmt == "llm":
        return format_hits_llm(items, anchor=anchor, instruction=instruction)
    if fmt == "text":
        return format_hits(items, color=color)
    raise ValueError(f"unknown output format: {fmt!r}")


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
