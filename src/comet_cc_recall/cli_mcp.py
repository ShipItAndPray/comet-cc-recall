"""CLI subcommand wiring for the MCP server.

Kept in a separate module from `cli.py` so the MCP SDK is only imported
when the user actually invokes `comet-cc-recall mcp` (the SDK pulls in
pydantic, anyio, starlette — heavy for a CLI that mostly does sub-second
RPC calls).
"""

from __future__ import annotations

import argparse


def add_subparser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    """Register the `mcp` subcommand on a parent argparse subparsers handle."""
    return subparsers.add_parser(
        "mcp",
        help="Run a Model Context Protocol server over stdio exposing recall tools.",
    )


def cmd_mcp(_args: argparse.Namespace, *, client=None) -> int:
    """Invoke the stdio MCP server.

    The optional `client` parameter is honored only for symmetry with the
    other CLI handlers; if provided, it becomes the default DaemonClient
    used by every tool.
    """
    from comet_cc_recall import mcp_server

    if client is not None:
        mcp_server.set_client(client)
    mcp_server.serve_stdio()
    return 0
