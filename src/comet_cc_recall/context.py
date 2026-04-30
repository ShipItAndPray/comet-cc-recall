"""Context-block emitter — `comet-cc-recall context <file>`.

Recalls hits for a file and renders them as a `<recalled-memory>` block
suitable for pasting at the top of a fresh Claude Code (or any agent)
prompt. Designed so the agent treats the block as authoritative recalled
context, exactly the way the upstream daemon's in-session retrieval
injection does."""

from __future__ import annotations

from pathlib import Path

from comet_cc_recall.anchor import build_anchor
from comet_cc_recall.client import DaemonClient
from comet_cc_recall.fmt import format_hits_llm
from comet_cc_recall.recall import (
    DEFAULT_MIN_SCORE,
    DEFAULT_TOP_K,
    RecallHit,
    recall,
)
from comet_cc_recall.repo import find_repo_root, relative_path, repo_name
from comet_cc_recall.symbols import extract_from_path

DEFAULT_INSTRUCTION = (
    "These memory nodes summarize prior reasoning about this file. "
    "Treat as recalled context; cite node ids when you rely on them."
)


def context_block(
    file_path: str | Path,
    *,
    client: DaemonClient | None = None,
    top_k: int = DEFAULT_TOP_K,
    min_score: float = DEFAULT_MIN_SCORE,
    instruction: str = DEFAULT_INSTRUCTION,
) -> str:
    """Recall + render as an LLM-paste block. Returns the empty string
    when there are no hits, so callers can `if out: print(out)`."""
    p = Path(file_path)
    hits: list[RecallHit] = recall(p, client=client, top_k=top_k, min_score=min_score)
    if not hits:
        return ""
    repo_root = find_repo_root(p)
    name = repo_name(repo_root, fallback=p)
    rel = relative_path(p, repo_root)
    lang, symbols = extract_from_path(p)
    anchor = build_anchor(repo=name, file_rel=rel, symbols=symbols, language=lang)
    return format_hits_llm(hits, anchor=anchor, instruction=instruction)
