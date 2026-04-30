"""Postprocess `RecallHit` lists by tag, importance, and recency.

All filters operate on the dataclass — no daemon round-trip — so they
compose freely with any subcommand that returns hits."""

from __future__ import annotations

import re
import time
from collections.abc import Iterable, Sequence
from datetime import datetime, timezone

from comet_cc_recall.recall import RecallHit

_VALID_IMPORTANCE = {"HIGH", "MED", "LOW"}

_DURATION_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([smhdw])\s*$", re.IGNORECASE)
_UNIT_SECONDS = {
    "s": 1,
    "m": 60,
    "h": 3600,
    "d": 86_400,
    "w": 604_800,
}


def parse_since(value: str | None, *, now: float | None = None) -> float | None:
    """Convert `--since` to a unix timestamp.

    Accepts either a duration shorthand (`30d`, `12h`, `90m`, `2w`, `45s`)
    or an ISO-8601 date/datetime (`2026-04-01`, `2026-04-01T12:00:00Z`).
    Returns the cutoff *timestamp*; nodes with `created_at >= cutoff` pass.
    None / empty input → None (no filter).
    """
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    m = _DURATION_RE.match(text)
    if m:
        amount = float(m.group(1))
        unit = m.group(2).lower()
        seconds = amount * _UNIT_SECONDS[unit]
        ref = now if now is not None else time.time()
        return ref - seconds
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as e:
        raise ValueError(f"unrecognized --since: {value!r} (try `30d` or `2026-04-01`)") from e
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def filter_hits(
    hits: Iterable[RecallHit],
    *,
    tags: Sequence[str] | None = None,
    importance: Sequence[str] | None = None,
    since: float | None = None,
) -> list[RecallHit]:
    """Apply tag / importance / since filters in order.

    - `tags`: any-match (a hit passes if it carries at least one of the
      requested tags). Case-insensitive.
    - `importance`: set membership (case-insensitive, validated).
    - `since`: only hits with `created_at >= since` survive.
    """
    tag_set = {t.strip().lower() for t in tags or [] if t and t.strip()}
    imp_raw = [i.strip().upper() for i in importance or [] if i and i.strip()]
    for i in imp_raw:
        if i not in _VALID_IMPORTANCE:
            raise ValueError(
                f"unknown importance {i!r} (expected one of {sorted(_VALID_IMPORTANCE)})"
            )
    imp_set = set(imp_raw)

    out: list[RecallHit] = []
    for h in hits:
        if tag_set and not (tag_set & {t.lower() for t in h.tags}):
            continue
        if imp_set and h.importance.upper() not in imp_set:
            continue
        if since is not None and h.created_at < since:
            continue
        out.append(h)
    return out
