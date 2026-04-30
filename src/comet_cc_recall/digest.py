"""Periodic digest aggregator — group memory nodes by tag.

Pulls every node from the daemon, filters to a time window and (optionally)
an importance allow-list, then groups parents by their dominant tag.
Useful for daily standups, weekly reviews, or "what was I thinking about
last week" overviews."""

from __future__ import annotations

import json
import sys
import time
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from comet_cc_recall.client import DaemonClient
from comet_cc_recall.filters import filter_hits, parse_since
from comet_cc_recall.recall import RecallHit

__all__ = [
    "DigestGroup",
    "Digest",
    "digest",
    "format_digest_text",
    "format_digest_md",
    "format_digest_json",
]

DEFAULT_UNTAGGED_LABEL = "_untagged"
DEFAULT_TOP_PER_TAG = 3
DEFAULT_SINCE = "7d"

_IMPORTANCE_RANK = {"HIGH": 0, "MED": 1, "LOW": 2}


@dataclass(frozen=True)
class DigestGroup:
    tag: str
    hits: tuple[RecallHit, ...]
    total_in_period: int


@dataclass(frozen=True)
class Digest:
    since: float
    until: float
    total_nodes: int
    groups: tuple[DigestGroup, ...]


def _is_child(node: dict[str, Any]) -> bool:
    parent = node.get("parent_node_id")
    return parent is not None and str(parent).strip() != ""


def _hit_sort_key(h: RecallHit) -> tuple[int, float]:
    rank = _IMPORTANCE_RANK.get((h.importance or "MED").upper(), 1)
    return (rank, -float(h.created_at or 0.0))


def _normalized_tags(hit: RecallHit) -> list[str]:
    return [t for t in hit.tags if t and t.strip()]


def _assign_group(
    tags: Sequence[str],
    *,
    tag_freq: Counter[str],
    untagged_label: str,
) -> str:
    candidates = [t for t in tags if t and t.strip()]
    if not candidates:
        return untagged_label
    return min(candidates, key=lambda t: (-tag_freq[t], t))


def _within_period(hit: RecallHit, *, since: float | None, until: float | None) -> bool:
    ts = float(hit.created_at or 0.0)
    if since is not None and ts < since:
        return False
    return not (until is not None and ts > until)


def digest(
    *,
    since: str = DEFAULT_SINCE,
    until: float | None = None,
    importance: list[str] | None = None,
    top_per_tag: int = DEFAULT_TOP_PER_TAG,
    max_groups: int | None = None,
    untagged_label: str = DEFAULT_UNTAGGED_LABEL,
    client: DaemonClient | None = None,
) -> Digest:
    """Build a tag-grouped digest of memory nodes in a time window.

    Parameters
    ----------
    since : str
        Duration shorthand (`7d`, `12h`) or ISO date — see `parse_since`.
    until : float, optional
        Upper-bound unix timestamp. Defaults to "now".
    importance : list[str], optional
        Restrict to one or more importance levels (HIGH/MED/LOW).
    top_per_tag : int
        How many hits to surface per group; `total_in_period` retains the
        full count.
    max_groups : int, optional
        Cap the number of groups returned. Untagged group is preserved.
    untagged_label : str
        Bucket label for nodes with no tags.
    client : DaemonClient, optional
        Defaults to `DaemonClient.default()`. Tests pass a fake.
    """
    cli = client or DaemonClient.default()
    until_ts = time.time() if until is None else float(until)
    since_ts = parse_since(since)
    if since_ts is None:
        since_ts = 0.0

    raw_nodes = cli.list_all_nodes()

    parents: list[dict[str, Any]] = [n for n in raw_nodes if not _is_child(n)]

    all_hits = [RecallHit.from_node_dict(n, score=1.0) for n in parents]

    period_hits = [
        h for h in filter_hits(all_hits, importance=importance, since=since_ts)
        if _within_period(h, since=since_ts, until=until_ts)
    ]

    tag_freq: Counter[str] = Counter()
    for h in period_hits:
        for t in _normalized_tags(h):
            tag_freq[t] += 1

    buckets: dict[str, list[RecallHit]] = {}
    for h in period_hits:
        tag = _assign_group(
            _normalized_tags(h), tag_freq=tag_freq, untagged_label=untagged_label
        )
        buckets.setdefault(tag, []).append(h)

    untagged_bucket = buckets.pop(untagged_label, None)

    tagged_groups: list[DigestGroup] = []
    for tag, hits in buckets.items():
        sorted_hits = sorted(hits, key=_hit_sort_key)
        truncated = tuple(sorted_hits[:top_per_tag]) if top_per_tag >= 0 else tuple(sorted_hits)
        tagged_groups.append(
            DigestGroup(tag=tag, hits=truncated, total_in_period=len(hits))
        )

    tagged_groups.sort(key=lambda g: (-g.total_in_period, g.tag))

    if max_groups is not None and max_groups >= 0:
        tagged_groups = tagged_groups[:max_groups]

    final_groups: list[DigestGroup] = list(tagged_groups)
    if untagged_bucket:
        sorted_untagged = sorted(untagged_bucket, key=_hit_sort_key)
        truncated = (
            tuple(sorted_untagged[:top_per_tag]) if top_per_tag >= 0 else tuple(sorted_untagged)
        )
        final_groups.append(
            DigestGroup(
                tag=untagged_label,
                hits=truncated,
                total_in_period=len(untagged_bucket),
            )
        )

    return Digest(
        since=since_ts,
        until=until_ts,
        total_nodes=len(period_hits),
        groups=tuple(final_groups),
    )


def _supports_color(stream=sys.stdout) -> bool:
    return hasattr(stream, "isatty") and stream.isatty()


def _c(text: str, code: str, *, on: bool) -> str:
    return f"\x1b[{code}m{text}\x1b[0m" if on else text


def _isodate(ts: float) -> str:
    if not ts:
        return ""
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")


def _period_label(d: Digest) -> str:
    start = _isodate(d.since) or "earliest"
    end = _isodate(d.until) or "now"
    return f"{start} → {end}"


def _truncate_summary(summary: str, *, limit: int = 120) -> str:
    text = (summary or "").strip().replace("\n", " ")
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def format_digest_text(d: Digest, *, color: bool | None = None) -> str:
    on = _supports_color() if color is None else color
    period = _period_label(d)
    header = _c(f"digest: {d.total_nodes} nodes over {period}", "1", on=on)
    lines: list[str] = [header]
    if not d.groups:
        lines.append(_c("no groups", "2", on=on))
        return "\n".join(lines)
    for g in d.groups:
        lines.append("")
        lines.append(
            _c(f"## {g.tag}", "36", on=on)
            + " "
            + _c(f"({g.total_in_period})", "2", on=on)
        )
        for h in g.hits:
            imp = _c(f"[{h.importance}]", "35", on=on)
            nid = _c(h.node_id, "33", on=on)
            summary = _truncate_summary(h.summary)
            lines.append(f"- {nid} {imp} {summary}".rstrip())
    return "\n".join(lines)


def format_digest_md(d: Digest) -> str:
    period = _period_label(d)
    out: list[str] = ["# Digest", "", f"_{d.total_nodes} nodes over {period}_", ""]
    if not d.groups:
        out.append("_no groups_")
        return "\n".join(out).rstrip() + "\n"
    if len(d.groups) > 5:
        out.append("## Contents")
        out.append("")
        for g in d.groups:
            out.append(f"- [{g.tag}](#{_md_anchor(g.tag)}) ({g.total_in_period})")
        out.append("")
    for g in d.groups:
        out.append(f"## {g.tag} ({g.total_in_period})")
        out.append("")
        if not g.hits:
            out.append("_no hits in window_")
            out.append("")
            continue
        for h in g.hits:
            summary = _truncate_summary(h.summary, limit=200)
            line = f"- `{h.node_id}` **{h.importance}**"
            if summary:
                line += f" — {summary}"
            out.append(line)
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def _md_anchor(tag: str) -> str:
    return tag.strip().lower().replace(" ", "-")


def _hit_payload(h: RecallHit) -> dict[str, Any]:
    return {
        "node_id": h.node_id,
        "summary": h.summary,
        "trigger": h.trigger,
        "importance": h.importance,
        "tags": list(h.tags),
        "session_id": h.session_id,
        "created_at": h.created_at,
    }


def _group_payload(g: DigestGroup) -> dict[str, Any]:
    return {
        "tag": g.tag,
        "total_in_period": g.total_in_period,
        "hits": [_hit_payload(h) for h in g.hits],
    }


def format_digest_json(d: Digest) -> str:
    payload = {
        "since": d.since,
        "until": d.until,
        "total_nodes": d.total_nodes,
        "groups": [_group_payload(g) for g in d.groups],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def format_digest_any(
    d: Digest,
    *,
    fmt: str,
    color: bool | None = None,
) -> str:
    if fmt == "json":
        return format_digest_json(d)
    if fmt == "md":
        return format_digest_md(d)
    if fmt == "text":
        return format_digest_text(d, color=color)
    raise ValueError(f"unknown digest output format: {fmt!r}")


