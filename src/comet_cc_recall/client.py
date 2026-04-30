"""Unix socket RPC client for the CoMeT-CC daemon.

Mirrors the wire format used by `comet_cc.client` so we don't need to
import upstream. Returns parsed dicts from the daemon, or `None` on any
connection failure (treat as "daemon not running").
"""

from __future__ import annotations

import json
import os
import socket
from collections.abc import Mapping
from pathlib import Path
from typing import Any


def daemon_socket_path() -> Path:
    """Path the upstream daemon listens on. Mirrors `comet_cc.config`."""
    home = os.environ.get("COMET_CC_HOME")
    base = Path(home) if home else Path.home() / ".comet-cc"
    return base / "daemon.sock"


def store_path() -> Path:
    home = os.environ.get("COMET_CC_HOME")
    base = Path(home) if home else Path.home() / ".comet-cc"
    return base / "store.sqlite"


class DaemonError(RuntimeError):
    """Raised when the daemon socket exists but the call failed in a way
    we can't transparently recover from."""


class DaemonClient:
    """Thin wrapper that knows how to call the upstream daemon's JSON-RPC.

    Constructor accepts `socket_path` for tests. Production callers can
    use `DaemonClient.default()`.
    """

    def __init__(self, socket_path: str | os.PathLike[str], *, timeout: float = 10.0):
        self.socket_path = Path(socket_path)
        self.timeout = timeout

    @classmethod
    def default(cls, *, timeout: float = 10.0) -> DaemonClient:
        return cls(daemon_socket_path(), timeout=timeout)

    def is_running(self) -> bool:
        if not self.socket_path.exists():
            return False
        r = self._rpc("ping", timeout=1.0)
        return bool(r and r.get("ok"))

    def get_context_window(
        self,
        *,
        session_id: str,
        query: str,
        max_nodes: int = 8,
        min_score: float = 0.30,
    ) -> list[dict[str, Any]]:
        """Embed `query` and cosine-search the store. Returns list of node
        dicts (summary, trigger, tags, etc.). Honors the daemon's existing
        `COMET_CC_CROSS_SESSION` setting."""
        r = self._rpc(
            "get_context_window",
            timeout=max(self.timeout, 10.0),
            session_id=session_id,
            query=query,
            max_nodes=max_nodes,
            min_score=min_score,
        )
        if r is None:
            raise DaemonError("daemon not reachable")
        if not r.get("ok"):
            raise DaemonError(r.get("error", "unknown daemon error"))
        nodes = r.get("nodes") or []
        if not isinstance(nodes, list):
            raise DaemonError(f"unexpected nodes payload: {type(nodes).__name__}")
        return nodes

    def read_memory(self, node_id: str, *, depth: int = 0) -> dict[str, Any]:
        """Tiered read. depth=0 summary, depth=1 detailed (haiku-cached),
        depth=2 raw turns."""
        r = self._rpc(
            "read_memory",
            timeout=self.timeout if depth == 0 else 120.0,
            node_id=node_id,
            depth=depth,
        )
        if r is None:
            raise DaemonError("daemon not reachable")
        if not r.get("ok"):
            raise DaemonError(r.get("error", "unknown daemon error"))
        return r

    def list_all_nodes(self) -> list[dict[str, Any]]:
        r = self._rpc("list_all_nodes", timeout=self.timeout)
        if r is None:
            raise DaemonError("daemon not reachable")
        if not r.get("ok"):
            raise DaemonError(r.get("error", "list_all_nodes failed"))
        return r.get("nodes") or []

    def get_node(self, node_id: str) -> dict[str, Any]:
        """Fetch a single node's metadata (no raw turns)."""
        r = self._rpc("get_node", timeout=self.timeout, node_id=node_id)
        if r is None:
            raise DaemonError("daemon not reachable")
        if not r.get("ok"):
            raise DaemonError(r.get("error", "get_node failed"))
        node = r.get("node")
        if not isinstance(node, dict):
            raise DaemonError("get_node returned no node")
        return node

    def list_linked_nodes(self, parent_id: str) -> list[dict[str, Any]]:
        """Return the children/peers linked from `parent_id` via the
        node-graph `links` edges."""
        r = self._rpc("list_linked_nodes", timeout=self.timeout, parent_id=parent_id)
        if r is None:
            raise DaemonError("daemon not reachable")
        if not r.get("ok"):
            raise DaemonError(r.get("error", "list_linked_nodes failed"))
        return r.get("nodes") or []

    # ---- transport ----

    def _rpc(self, method: str, *, timeout: float, **params: Any) -> Mapping[str, Any] | None:
        if not self.socket_path.exists():
            return None
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                s.settimeout(timeout)
                s.connect(str(self.socket_path))
                req = json.dumps({"method": method, "params": params}, ensure_ascii=False)
                s.sendall(req.encode("utf-8") + b"\n")
                s.shutdown(socket.SHUT_WR)
                buf = bytearray()
                while True:
                    chunk = s.recv(65536)
                    if not chunk:
                        break
                    buf += chunk
            if not buf:
                return None
            return json.loads(buf.decode("utf-8"))
        except (FileNotFoundError, ConnectionRefusedError, OSError, json.JSONDecodeError):
            return None
