"""Model Context Protocol (MCP) server for comet-cc-recall.

Exposes the existing recall/search/related/diff/context/read surfaces as
MCP tools over stdio. Built on the official Python SDK's `FastMCP` API
(higher-level than the raw `Server` class — declarative tool registration
via decorator, automatic JSON-Schema generation from type hints).

Each tool is also importable as a plain Python callable, so tests can
exercise the wrapper logic without spinning up an MCP transport. The
module-level `_default_client` is overridable via `set_client()` for tests
or for embedders that already hold a configured `DaemonClient`.

Errors from the daemon never propagate out of a tool call — they're
serialized as `{"error": "<message>"}` so the LLM-side caller sees a
structured failure rather than an MCP-level transport exception.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from mcp.server.fastmcp import FastMCP

from comet_cc_recall.client import DaemonClient, DaemonError
from comet_cc_recall.context import context_block as _context_block
from comet_cc_recall.diff import diff_recall as _diff_recall
from comet_cc_recall.recall import RecallHit
from comet_cc_recall.recall import recall as _recall
from comet_cc_recall.related import related as _related
from comet_cc_recall.search import search as _search

__all__ = [
    "build_server",
    "context_block",
    "diff_recall",
    "read_node",
    "recall_file",
    "related",
    "search",
    "serve_stdio",
    "set_client",
]

_default_client: DaemonClient | None = None


def set_client(client: DaemonClient | None) -> None:
    """Override the DaemonClient used by every tool. Pass None to clear."""
    global _default_client
    _default_client = client


def _client() -> DaemonClient:
    return _default_client if _default_client is not None else DaemonClient.default()


def _hit_to_dict(h: RecallHit) -> dict[str, Any]:
    d = asdict(h)
    d["tags"] = list(h.tags)
    d["created_at"] = float(h.created_at)
    return d


def _hits(hits: list[RecallHit]) -> list[dict[str, Any]]:
    return [_hit_to_dict(h) for h in hits]


def recall_file(path: str, top_k: int = 5) -> list[dict[str, Any]] | dict[str, str]:
    """Recall memory nodes anchored to a source file.

    Extracts symbols and language from the file, builds a structured anchor
    query, asks the daemon for matching nodes, then reranks by repo
    proximity. Returns a list of node dicts (node_id, score, summary,
    trigger, importance, tags, session_id, created_at) sorted by score
    descending. Returns an empty list for unsupported file types.
    """
    try:
        hits = _recall(path, client=_client(), top_k=top_k)
    except DaemonError as e:
        return {"error": str(e)}
    return _hits(hits)


def search(query: str, top_k: int = 5) -> list[dict[str, Any]] | dict[str, str]:
    """Raw semantic search over memory nodes by free-text query.

    Use when you don't have a file open or want to recall by description
    rather than by code surface (e.g. "redis idempotency race"). Returns
    the top-K nodes by cosine similarity.
    """
    try:
        hits = _search(query, client=_client(), top_k=top_k)
    except DaemonError as e:
        return {"error": str(e)}
    return _hits(hits)


def related(
    node_id: str,
    depth: int = 1,
    top_k: int = 8,
) -> list[dict[str, Any]] | dict[str, str]:
    """Walk the memory-node graph from a seed node id.

    depth=1 returns direct linked peers (score 1.0). depth=2 also pulls
    each hop-1 node's links (score 0.6) and dedupes. The seed is excluded
    from results.
    """
    try:
        hits = _related(node_id, client=_client(), depth=depth, top_k=top_k)
    except DaemonError as e:
        return {"error": str(e)}
    return _hits(hits)


def diff_recall(
    base: str | None = None,
    top_k: int = 5,
) -> list[dict[str, Any]] | dict[str, str]:
    """Recall against the union of files changed in `git diff`.

    `base` defaults to None (working tree vs HEAD plus untracked files).
    Pass a ref like "main" or "HEAD~3" to compare against that. Hits from
    each changed file are merged keeping the max score per node id.
    """
    try:
        hits = _diff_recall(base, client=_client(), top_k=top_k)
    except DaemonError as e:
        return {"error": str(e)}
    return _hits(hits)


def context_block(path: str, top_k: int = 5) -> dict[str, str]:
    """Render a `<recalled-memory>` XML block to paste into a fresh agent.

    Recalls hits for `path` and formats them with anchor + instruction
    metadata. Returns `{"block": "<xml...>"}` on success, `{"block": ""}`
    when there are no hits, or `{"error": "..."}` on daemon failure.
    """
    try:
        block = _context_block(path, client=_client(), top_k=top_k)
    except DaemonError as e:
        return {"error": str(e)}
    return {"block": block}


def read_node(node_id: str, depth: int = 0) -> dict[str, Any]:
    """Read a memory node at depth 0 (summary), 1 (detailed), or 2 (raw turns).

    Thin pass-through to the daemon's `read_memory` RPC. Returns the
    daemon's payload dict, or `{"error": "..."}` on failure.
    """
    try:
        return dict(_client().read_memory(node_id, depth=depth))
    except DaemonError as e:
        return {"error": str(e)}


def build_server() -> FastMCP:
    """Construct a FastMCP instance with all six recall tools registered."""
    server: FastMCP = FastMCP(
        name="comet-cc-recall",
        instructions=(
            "File-anchored memory recall for CoMeT-CC. Use recall_file when "
            "you have a source path; search for free-text queries; related "
            "to walk from a known node id; diff_recall against the current "
            "git diff; context_block to emit a paste-ready prompt block; "
            "read_node to fetch a node's full payload."
        ),
    )
    server.add_tool(
        recall_file,
        name="recall_file",
        description=(
            "Recall memory nodes anchored to a source file by extracting "
            "symbols + language and ranking by semantic + repo proximity."
        ),
    )
    server.add_tool(
        search,
        name="search",
        description="Raw semantic search over memory nodes by free-text query.",
    )
    server.add_tool(
        related,
        name="related",
        description="Walk the memory graph from a seed node id (depth 1 or 2).",
    )
    server.add_tool(
        diff_recall,
        name="diff_recall",
        description="Recall against the union of files changed in git diff.",
    )
    server.add_tool(
        context_block,
        name="context_block",
        description="Render a <recalled-memory> XML block to paste into a fresh agent.",
    )
    server.add_tool(
        read_node,
        name="read_node",
        description="Read a memory node at depth 0 (summary), 1 (detailed), or 2 (raw turns).",
    )
    return server


def serve_stdio() -> None:  # pragma: no cover - I/O entrypoint
    """Run the MCP server over stdio. Blocks until the transport closes."""
    build_server().run("stdio")
