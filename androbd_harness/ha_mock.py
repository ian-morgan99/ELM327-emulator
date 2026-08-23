#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Mock Home Assistant REST API server.

Implements just enough of the Home Assistant HTTP API for the
AndrOBD-Plugin-Home-Assistant project to be tested end-to-end without a real
HA instance:

  * ``POST /api/states/<entity_id>`` - create/update an entity state.
    The HA plugin posts JSON::

        {
          "state": "<value>",
          "attributes": {
              "friendly_name": "<key>",
              "source": "AndrOBD",
              "timestamp": <epoch ms>
          }
        }

    with an ``Authorization: Bearer <token>`` header.  Real HA answers with
    HTTP 200 and a JSON array containing the updated entity; this mock does
    the same, and additionally records every update so tests can assert on
    what the plugin sent.

  * ``GET /api/`` - returns 200 (HA's "is HA running?" probe).
  * ``GET /api/states/<entity_id>`` - returns the last recorded state.

Authentication: when a token is configured, requests without a matching
``Authorization: Bearer <token>`` header get HTTP 401, exactly like HA.

The server uses only the standard library (``http.server``), so it runs in
any environment.  It is thread-safe and records updates in memory; optionally
they can be mirrored to a JSONL file for post-mortem inspection.
"""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Dict, List, Optional


class HaMockServer:
    """A mock of the Home Assistant REST API (see module docstring).

    Parameters
    ----------
    host :
        Bind address (default ``127.0.0.1``).
    port :
        Port to listen on.  Pass ``0`` to let the OS pick a free port; the
        actual port is available as :attr:`port` after :meth:`start`.
    token :
        Expected bearer token.  When ``None``, authentication is disabled.
    jsonl_path :
        Optional path; when given, every received update is appended to this
        file as one JSON object per line.
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 0,
                 token: Optional[str] = None,
                 jsonl_path: Optional[str] = None):
        self.host = host
        self.port = port  # updated to the OS-assigned port after start()
        self.token = token
        self.jsonl_path = jsonl_path
        self._server: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        # entity_id -> {"state": str, "attributes": dict, "last_update": float}
        self.states: Dict[str, dict] = {}
        # Chronological log of every POST received.
        self.updates: List[dict] = []
        self._lock = threading.Lock()
        self.request_count = 0
        self.auth_failures = 0

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #
    def start(self) -> "HaMockServer":
        handler = _make_handler(self)
        self._server = ThreadingHTTPServer((self.host, self.port), handler)
        self._server.daemon_threads = True
        self.port = self._server.server_address[1]
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="ha-mock-server", daemon=True)
        self._thread.start()
        return self

    def stop(self):
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()

    @property
    def url(self) -> str:
        """Base URL the HA plugin should be configured with (``ha_url``)."""
        return f"http://{self.host}:{self.port}"

    # ------------------------------------------------------------------ #
    # Introspection helpers for tests
    # ------------------------------------------------------------------ #
    def get_state(self, entity_id: str) -> Optional[dict]:
        with self._lock:
            return self.states.get(entity_id)

    def updates_for(self, entity_id: str) -> List[dict]:
        with self._lock:
            return [u for u in self.updates if u["entity"] == entity_id]

    def wait_for_update(self, entity_id: str, timeout: float = 10.0,
                        predicate=None) -> Optional[dict]:
        """Block until an update for ``entity_id`` arrives (or predicate
        matches).  Returns the update dict or ``None`` on timeout."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._lock:
                candidates = [u for u in self.updates
                              if u["entity"] == entity_id]
            if candidates:
                if predicate is None or any(predicate(u) for u in candidates):
                    return candidates[-1]
            time.sleep(0.05)
        return None


def _make_handler(server: HaMockServer):
    class Handler(BaseHTTPRequestHandler):
        # Silence default request logging.
        def log_message(self, fmt, *args):  # noqa: N802
            pass

        # ---------------------------------------------------------- #
        # Helpers
        # ---------------------------------------------------------- #
        def _send_json(self, code: int, payload):
            body = json.dumps(payload).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _authorized(self) -> bool:
            if server.token is None:
                return True
            auth = self.headers.get("Authorization", "")
            return auth == f"Bearer {server.token}"

        # ---------------------------------------------------------- #
        # Routes
        # ---------------------------------------------------------- #
        def do_GET(self):  # noqa: N802
            path = self.path.rstrip("/") or "/"
            if path in ("/api", "/"):
                self._send_json(200, {"message": "mock HA"})
                return
            if path.startswith("/api/states/"):
                entity = path[len("/api/states/"):]
                with server._lock:
                    state = server.states.get(entity)
                if state is None:
                    self._send_json(404, {"message": "entity not found"})
                else:
                    # HA returns a list of entity state objects.
                    self._send_json(200, [{
                        "entity_id": entity,
                        "state": state["state"],
                        "attributes": state["attributes"],
                    }])
                return
            self._send_json(404, {"message": "not found"})

        def do_POST(self):  # noqa: N802
            path = self.path.rstrip("/") or "/"
            if not path.startswith("/api/states/"):
                self._send_json(404, {"message": "not found"})
                return
            entity = path[len("/api/states/"):]

            with server._lock:
                server.request_count += 1

            if not self._authorized():
                with server._lock:
                    server.auth_failures += 1
                self._send_json(401, {"message": "Unauthorized"})
                return

            try:
                length = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(length) if length else b"{}"
                payload = json.loads(raw.decode("utf-8") or "{}")
            except (ValueError, json.JSONDecodeError):
                self._send_json(400, {"message": "invalid JSON"})
                return

            state_value = str(payload.get("state", ""))
            attributes = payload.get("attributes", {}) or {}
            record = {
                "entity": entity,
                "state": state_value,
                "attributes": attributes,
                "received_at": time.time(),
            }
            with server._lock:
                server.states[entity] = {
                    "state": state_value,
                    "attributes": attributes,
                    "last_update": record["received_at"],
                }
                server.updates.append(record)
            if server.jsonl_path is not None:
                try:
                    with open(server.jsonl_path, "a", encoding="utf-8") as f:
                        f.write(json.dumps(record) + "\n")
                except OSError:
                    pass

            # Real HA answers 200 with a list containing the new state.
            self._send_json(200, [{
                "entity_id": entity,
                "state": state_value,
                "attributes": attributes,
            }])

    return Handler
