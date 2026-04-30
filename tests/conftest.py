"""Shared fixtures: a fake Unix-socket RPC server that mimics the upstream
CoMeT-CC daemon's wire protocol just enough to exercise our client + recall
pipeline end-to-end.
"""

from __future__ import annotations

import contextlib
import json
import socket
import tempfile
import threading
import uuid
from collections.abc import Callable
from pathlib import Path

import pytest

from comet_cc_recall.client import DaemonClient


def _short_socket_path() -> Path:
    """Return a path short enough for macOS's ~104-byte AF_UNIX limit.

    pytest's tmp_path lives under /private/var/folders/... which already
    eats most of the budget; a separate /tmp dir keeps us well clear.
    """
    base = Path(tempfile.gettempdir()) / "ccr-t"
    base.mkdir(parents=True, exist_ok=True)
    return base / f"{uuid.uuid4().hex[:10]}.sock"


class FakeDaemon:
    """Minimal Unix-socket JSON-RPC server matching upstream's framing.

    Wire format (line-delimited):
        client → server: one JSON object, then half-close (SHUT_WR)
        server → client: one JSON object, then close

    Handlers are method-name → callable(params: dict) -> dict.
    """

    def __init__(self, socket_path: Path, handlers: dict[str, Callable[[dict], dict]]):
        self.socket_path = socket_path
        self.handlers = handlers
        self._sock: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.calls: list[tuple[str, dict]] = []

    def start(self) -> None:
        if self.socket_path.exists():
            self.socket_path.unlink()
        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._sock.bind(str(self.socket_path))
        self._sock.listen(8)
        self._sock.settimeout(0.5)
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._sock is not None:
            with contextlib.suppress(OSError):
                self._sock.close()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        if self.socket_path.exists():
            with contextlib.suppress(FileNotFoundError):
                self.socket_path.unlink()

    def _serve(self) -> None:
        assert self._sock is not None
        while not self._stop.is_set():
            try:
                conn, _ = self._sock.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            with conn:
                conn.settimeout(2.0)
                buf = bytearray()
                try:
                    while True:
                        chunk = conn.recv(65536)
                        if not chunk:
                            break
                        buf += chunk
                except OSError:
                    continue
                if not buf:
                    continue
                try:
                    req = json.loads(buf.decode("utf-8"))
                except json.JSONDecodeError:
                    resp = {"ok": False, "error": "bad json"}
                else:
                    method = req.get("method", "")
                    params = req.get("params") or {}
                    self.calls.append((method, params))
                    handler = self.handlers.get(method)
                    if handler is None:
                        resp = {"ok": False, "error": f"unknown method {method}"}
                    else:
                        try:
                            resp = handler(params)
                        except Exception as e:  # pragma: no cover - defensive
                            resp = {"ok": False, "error": f"{type(e).__name__}: {e}"}
                with contextlib.suppress(OSError):
                    conn.sendall(json.dumps(resp, ensure_ascii=False).encode("utf-8"))


@pytest.fixture
def fake_daemon(tmp_path: Path):
    """Yield a (DaemonClient, FakeDaemon) pair backed by a tmp Unix socket."""

    def _factory(handlers: dict[str, Callable[[dict], dict]]):
        sock_path = _short_socket_path()
        srv = FakeDaemon(sock_path, handlers)
        srv.start()
        return DaemonClient(sock_path, timeout=2.0), srv

    daemons: list[FakeDaemon] = []

    def factory(handlers: dict[str, Callable[[dict], dict]]):
        client, srv = _factory(handlers)
        daemons.append(srv)
        return client, srv

    yield factory
    for srv in daemons:
        srv.stop()


@pytest.fixture
def sample_python(tmp_path: Path) -> Path:
    src = '''
"""payments idempotency module."""

import time

GLOBAL_TTL = 60


class IdempotencyKey:
    def __init__(self, key: str) -> None:
        self.key = key

    def is_expired(self, now: float) -> bool:
        return now > GLOBAL_TTL


def reserve_key(key: str) -> bool:
    """Reserve a key in redis via SETNX with TTL."""
    return True


async def release_key(key: str) -> None:
    pass


def _internal_helper() -> None:
    """Underscore-prefixed; should be skipped by the extractor."""
'''
    p = tmp_path / "payments.py"
    p.write_text(src.lstrip(), encoding="utf-8")
    return p


@pytest.fixture
def sample_typescript(tmp_path: Path) -> Path:
    src = """
export interface User { id: string; }

export type Token = string;

export function login(user: User): Token {
    return "tok";
}

export const fetchUser = async (id: string): Promise<User> => ({ id });

export class AuthService {
    constructor() {}
}
"""
    p = tmp_path / "auth.ts"
    p.write_text(src.lstrip(), encoding="utf-8")
    return p


@pytest.fixture
def sample_go(tmp_path: Path) -> Path:
    src = """
package main

import "fmt"

type Server struct {
    addr string
}

func NewServer(addr string) *Server {
    return &Server{addr: addr}
}

func (s *Server) Listen() error {
    fmt.Println(s.addr)
    return nil
}
"""
    p = tmp_path / "server.go"
    p.write_text(src.lstrip(), encoding="utf-8")
    return p


@pytest.fixture
def fake_repo(tmp_path: Path) -> Path:
    """A directory with a `.git` marker so `find_repo_root` resolves."""
    repo = tmp_path / "myrepo"
    repo.mkdir()
    (repo / ".git").mkdir()
    return repo
