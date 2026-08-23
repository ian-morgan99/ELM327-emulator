#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AndrOBD application simulator.

This class emulates what the *real* AndrOBD Android app does, so the whole
pipeline can be exercised on a desktop without a phone:

    ELM327-emulator  <--TCP-->  AndrobdSimulator  --HTTP-->  Home Assistant
        (adapter)                 (this class)                (mock or real)

Concretely it:

  1. connects to the ELM327 adapter (the emulator) with :class:`ELM327Client`,
     performing the same AT setup the app performs (``ATZ``, ``ATSP 0``);
  2. polls a configurable set of OBD PIDs on a timer;
  3. decodes each raw response with the *exact* AndrOBD formulas
     (:mod:`pids`), producing the same ``key=value`` pairs the app would;
  4. pushes every value to Home Assistant using the *exact* HTTP contract of
     the AndrOBD-Plugin-Home-Assistant project (entity-id construction, JSON
     body, bearer-token auth) - see :meth:`push_to_ha`.

It can target either a :class:`~androbd_harness.ha_mock.HaMockServer` (for
closed-loop tests) or a real Home Assistant instance (``ha_url`` + token),
which is how you would validate the actual plugin end-to-end.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.request
import urllib.error
from typing import Callable, Dict, List, Optional

from .elm_client import ELM327Client
from .pids import PID_TABLE, DEFAULT_PIDS, decode_pid, format_value


def build_entity_id(key: str, prefix: str = "sensor.androbd_") -> str:
    """Reproduce the HA plugin's entity-id construction exactly.

    Mirrors ``HomeAssistantPlugin.sendSensorUpdate``::

        entityId = entityPrefix + key.toLowerCase()
                .replaceAll("[^a-z0-9_]", "_").replaceAll("_+", "_");
    """
    import re
    cleaned = key.lower()
    cleaned = re.sub(r"[^a-z0-9_]", "_", cleaned)
    cleaned = re.sub(r"_+", "_", cleaned)
    return prefix + cleaned


class AndrobdSimulator:
    """Emulates the AndrOBD app: poll PIDs from an ELM327 adapter and push
    decoded values to Home Assistant.

    Parameters
    ----------
    host, port :
        TCP endpoint of the ELM327 adapter / emulator.
    pids :
        List of OBD PID ints to poll (default :data:`DEFAULT_PIDS`).
    interval :
        Seconds between poll cycles (default 1.0).
    ha_url :
        Base URL of Home Assistant (e.g. ``http://127.0.0.1:8123``).  When
        ``None``, updates are only recorded in :attr:`last_values` and passed
        to ``on_update`` - no HTTP is performed.
    ha_token :
        Bearer token for Home Assistant.
    entity_prefix :
        Entity-id prefix (default ``sensor.androbd_``), matching the plugin's
        ``PREF_HA_ENTITY_PREFIX`` default.
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 35000,
                 pids: Optional[List[int]] = None, interval: float = 1.0,
                 ha_url: Optional[str] = None, ha_token: Optional[str] = None,
                 entity_prefix: str = "sensor.androbd_"):
        self.host = host
        self.port = port
        self.pids = list(pids) if pids is not None else list(DEFAULT_PIDS)
        self.interval = interval
        self.ha_url = ha_url.rstrip("/") if ha_url else None
        self.ha_token = ha_token
        self.entity_prefix = entity_prefix

        self.client: Optional[ELM327Client] = None
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

        # Latest decoded values, keyed by AndrOBD mnemonic.
        self.last_values: Dict[str, str] = {}
        # Chronological history of (timestamp, {mnemonic: value}) snapshots.
        self.history: List[Dict[str, str]] = []
        # Counters for diagnostics / tests.
        self.poll_count = 0
        self.ha_posts = 0
        self.ha_errors = 0
        # Optional callback invoked with each decoded snapshot.
        self.on_update: Optional[Callable[[Dict[str, str]], None]] = None

    # ------------------------------------------------------------------ #
    # Connection / lifecycle
    # ------------------------------------------------------------------ #
    def connect(self) -> "AndrobdSimulator":
        self.client = ELM327Client(host=self.host, port=self.port).connect()
        # Same AT setup the real app performs on connect.
        try:
            self.client.reset()          # ATZ
            self.client.set_protocol(0)  # ATSP 0 (auto-detect)
            self.client.set_linefeed(1)  # ATL1
        except Exception:
            # Non-fatal: some adapters/emulators answer differently.
            pass
        return self

    def close(self):
        self.stop()
        if self.client is not None:
            self.client.close()
            self.client = None

    def __enter__(self):
        return self.connect()

    def __exit__(self, *exc):
        self.close()

    # ------------------------------------------------------------------ #
    # Polling
    # ------------------------------------------------------------------ #
    def poll_once(self) -> Dict[str, str]:
        """Poll every configured PID once and return the decoded snapshot.

        Decoding uses AndrOBD's exact formulas; values are formatted with
        AndrOBD's printf formats, so ``snapshot['vehicle_speed']`` is exactly
        the string the app would hand to ``onDataUpdate``.
        """
        if self.client is None:
            raise RuntimeError("Not connected - call connect() first")
        snapshot: Dict[str, str] = {}
        for pid in self.pids:
            spec = PID_TABLE.get(pid)
            if spec is None:
                continue
            try:
                raw = self.client.request_pid(
                    pid, extended_header=spec["header"])
            except Exception:
                snapshot[spec["mnemonic"]] = "N/A"
                continue
            value = decode_pid(pid, raw)
            snapshot[spec["mnemonic"]] = format_value(pid, value)
        self.last_values = snapshot
        self.history.append(snapshot)
        self.poll_count += 1
        if self.on_update is not None:
            self.on_update(snapshot)
        return snapshot

    def run(self, duration: Optional[float] = None,
            push_to_ha: bool = True):
        """Blocking poll loop.  Returns when ``duration`` elapses or
        :meth:`stop` is called."""
        start = time.time()
        while not self._stop.is_set():
            if duration is not None and time.time() - start >= duration:
                break
            snapshot = self.poll_once()
            if push_to_ha and self.ha_url:
                self.push_to_ha(snapshot)
            # Sleep in small slices so stop() is responsive.
            deadline = time.time() + self.interval
            while not self._stop.is_set() and time.time() < deadline:
                time.sleep(min(0.1, max(0.0, deadline - time.time())))

    def start(self, duration: Optional[float] = None,
              push_to_ha: bool = True) -> threading.Thread:
        """Run the poll loop in a background daemon thread."""
        self._stop.clear()
        self._thread = threading.Thread(
            target=self.run, args=(duration, push_to_ha),
            name="androbd-sim", daemon=True)
        self._thread.start()
        return self._thread

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    # ------------------------------------------------------------------ #
    # Home Assistant push (mirrors the HA plugin exactly)
    # ------------------------------------------------------------------ #
    def push_to_ha(self, snapshot: Dict[str, str]) -> int:
        """POST every value in ``snapshot`` to Home Assistant.

        Reproduces ``HomeAssistantPlugin.sendSensorUpdate``: for each key it
        builds the entity id, posts JSON ``{"state": value, "attributes":
        {"friendly_name": key, "source": "AndrOBD", "timestamp": ms}}`` with
        a bearer token.  Returns the number of successful posts.
        """
        if not self.ha_url:
            return 0
        sent = 0
        ts_ms = int(time.time() * 1000)
        for key, value in snapshot.items():
            entity_id = build_entity_id(key, self.entity_prefix)
            url = f"{self.ha_url}/api/states/{entity_id}"
            body = json.dumps({
                "state": value,
                "attributes": {
                    "friendly_name": key,
                    "source": "AndrOBD",
                    "timestamp": ts_ms,
                },
            }).encode("utf-8")
            req = urllib.request.Request(url, data=body, method="POST")
            req.add_header("Content-Type", "application/json")
            if self.ha_token:
                req.add_header("Authorization", f"Bearer {self.ha_token}")
            try:
                with urllib.request.urlopen(req, timeout=5) as resp:
                    if 200 <= resp.status < 300:
                        sent += 1
                        self.ha_posts += 1
                    else:
                        self.ha_errors += 1
            except (urllib.error.URLError, OSError):
                self.ha_errors += 1
        return sent
