#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ELM327 protocol client.

This is the *client* side of the ELM327 adapter protocol — i.e. exactly what
the AndrOBD Android app does when it connects to an adapter over WiFi (TCP) or
a serial/USB link.  It can talk to:

  * the ELM327-emulator in this repository (``Elm(net_port=...)``), and
  * a real ELM327 / OBDLink / Vgate / KWP2000 adapter.

The client is deliberately low-level and dependency-free (only the standard
library) so it can be embedded in tests, the driving simulator, or the
AndrOBD simulator without pulling in extra packages.

Protocol notes (ELM327):
  * AT commands are terminated by a newline; the adapter replies ``OK`` or
    ``ERROR`` (plus optional info).
  * OBD requests are sent as hex strings, e.g. ``010C`` (mode 01, PID 0x0C)
    or ``7E8 01 A6`` (ISO-TP extended header + mode 01, PID 0xA6).
  * Responses are space-separated hex bytes, e.g. ``41 0C 09 B0``.
  * Line-feed behaviour is controlled by the ``ATL`` command; AndrOBD uses
    ``ATL1`` (LF only) or ``ATL2`` (CR+LF).  This client strips both.
"""

from __future__ import annotations

import re
import socket
import time
from typing import List, Optional


class ELMError(Exception):
    """Raised when the adapter returns ERROR or a malformed response."""


# Matches a single OBD data byte in a response line: 0x00-0xFF in hex.
_HEX_BYTE = re.compile(r"^[0-9A-Fa-f]{2}$")


class ELM327Client:
    """A minimal but faithful ELM327 protocol client.

    Parameters
    ----------
    host, port :
        TCP endpoint of the adapter (or emulator).  When ``serial_port`` is
        given instead, a pyserial connection is used.
    serial_port :
        A serial device path (e.g. ``/dev/ttyUSB0``) or an already-opened
        pyserial ``Serial`` instance.
    timeout :
        Socket / read timeout in seconds.
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 35000,
                 serial_port=None, timeout: float = 5.0):
        self.host = host
        self.port = port
        self.serial_port = serial_port
        self.timeout = timeout
        self._sock: Optional[socket.socket] = None
        self._ser = None
        self._buf = b""

    # ------------------------------------------------------------------ #
    # Connection management
    # ------------------------------------------------------------------ #
    def connect(self) -> "ELM327Client":
        if self.serial_port is not None:
            self._open_serial()
        else:
            self._open_tcp()
        return self

    def _open_tcp(self):
        self._sock = socket.create_connection((self.host, self.port),
                                              timeout=self.timeout)
        self._sock.settimeout(self.timeout)

    def _open_serial(self):
        try:
            import serial  # pyserial
        except ImportError as exc:  # pragma: no cover - optional dep
            raise ELMError("pyserial is required for serial connections") from exc
        if isinstance(self.serial_port, str):
            self._ser = serial.Serial(self.serial_port, 115200, timeout=self.timeout)
        else:
            self._ser = self.serial_port

    def close(self):
        if self._sock is not None:
            try:
                self._sock.close()
            finally:
                self._sock = None
        if self._ser is not None:
            try:
                self._ser.close()
            finally:
                self._ser = None

    def __enter__(self):
        return self.connect()

    def __exit__(self, *exc):
        self.close()

    # ------------------------------------------------------------------ #
    # Low-level I/O
    # ------------------------------------------------------------------ #
    def _write(self, data: str):
        payload = data.encode("ascii")
        if self._sock is not None:
            self._sock.sendall(payload)
        else:
            self._ser.write(payload)

    def _read_line(self) -> str:
        """Read until a line terminator, returning the raw (unstripped) line.

        ELM327 adapters terminate lines with CR, LF or CRLF depending on the
        ``ATL`` mode; the emulator's default is CR-only.  We treat any of the
        three as a terminator so the client works against all of them.
        """
        while not re.search(rb"[\r\n]", self._buf):
            chunk = self._recv()
            if not chunk:
                break
            self._buf += chunk
        m = re.search(rb"[\r\n]", self._buf)
        if m is not None:
            line, rest = self._buf[:m.start()], self._buf[m.end():]
            # A CRLF terminator must be consumed as a unit.
            if m.group() == b"\r" and rest.startswith(b"\n"):
                rest = rest[1:]
            self._buf = rest
            return line.decode("ascii", "replace")
        # No terminator yet; return whatever we have (caller decides).
        out, self._buf = self._buf, b""
        return out.decode("ascii", "replace")

    def _recv(self) -> bytes:
        if self._sock is not None:
            return self._sock.recv(1024)
        n = self._ser.in_waiting or 0
        if n:
            return self._ser.read(n)
        time.sleep(0.01)
        return b""

    def _flush(self):
        self._buf = b""

    # ------------------------------------------------------------------ #
    # AT commands
    # ------------------------------------------------------------------ #
    def at(self, command: str, expect: Optional[str] = None) -> str:
        """Send an AT command and return the full response text.

        ``command`` should include the leading ``AT`` (e.g. ``"ATZ"``,
        ``"ATSP 0"``).  If ``expect`` is given, the response must contain it,
        otherwise :class:`ELMError` is raised.
        """
        self._flush()
        self._write(command + "\r\n")
        # ELM327 replies with a single line (or a few for ATI).  Read until we
        # see a line that is not part of a multi-line info block.
        lines: List[str] = []
        deadline = time.time() + self.timeout
        while time.time() < deadline:
            line = self._read_line().lstrip(">").strip()
            if line == "":
                continue
            # With echo enabled (the emulator's default) the adapter first
            # echoes the command back; drop that line so callers only see the
            # actual response.
            if line.upper() == command.upper():
                continue
            lines.append(line)
            # The emulator answers every AT command with a single line
            # ("OK", "ERROR", or the ATI version string); stop after it.
            break
        text = "\n".join(lines)
        if expect is not None and expect not in text:
            raise ELMError(f"AT {command!r}: expected {expect!r} in {text!r}")
        return text

    def reset(self) -> str:
        """ATZ - reset the adapter to defaults."""
        return self.at("ATZ")

    def info(self) -> str:
        """ATI - adapter identification."""
        return self.at("ATI")

    def set_protocol(self, protocol: int = 0) -> str:
        """ATSP <n> - select the OBD protocol (0 = auto-detect)."""
        return self.at(f"ATSP {protocol}")

    def set_linefeed(self, mode: int = 1) -> str:
        """ATL<n> - line-feed mode (0=none, 1=LF, 2=CR+LF)."""
        return self.at(f"ATL{mode}")

    def set_header(self, on: bool = True) -> str:
        """ATH<n> - include the ISO-TP header in responses."""
        return self.at(f"ATH{1 if on else 0}")

    # ------------------------------------------------------------------ #
    # OBD PID requests
    # ------------------------------------------------------------------ #
    def request_pid(self, pid: int, mode: int = 0x01,
                   extended_header: Optional[int] = None) -> List[int]:
        """Request a single OBD-II PID and return the response data bytes.

        ``pid`` is the 8-bit PID (e.g. ``0x0C`` for engine RPM).  ``mode`` is
        the OBD mode byte (default ``0x01`` = current data).  When
        ``extended_header`` is supplied (e.g. ``0x7E8``) an ISO-TP header is
        prepended, which is required for PIDs that live in the extended
        address space (such as the odometer, PID 0xA6).

        Returns the list of data bytes *after* the mode+PID echo, e.g. for
        ``41 0C 09 B0`` it returns ``[0x09, 0xB0]``.
        """
        if extended_header is not None:
            cmd = f"{extended_header:02X} {mode:02X}{pid:02X}"
        else:
            cmd = f"{mode:02X}{pid:02X}"
        self._flush()
        self._write(cmd + "\r\n")
        deadline = time.time() + self.timeout
        raw_lines: List[str] = []
        while time.time() < deadline:
            # The emulator glues its "> " prompt onto the start of the next
            # line; strip it (and any leading whitespace) before parsing.
            line = self._read_line().lstrip(">").strip()
            if line == "":
                continue
            raw_lines.append(line)
            # A valid OBD response is a single line of hex bytes.  Stop as soon
            # as we have one that looks like data (starts with the mode echo).
            tokens = line.split()
            if tokens and all(_HEX_BYTE.match(t) for t in tokens):
                break
        if not raw_lines:
            raise ELMError(f"PID {pid:#04x}: no response")
        # Take the last hex-looking line (skip any "NO DATA" / "BUSY" lines).
        data_line = None
        for line in reversed(raw_lines):
            tokens = line.split()
            if tokens and all(_HEX_BYTE.match(t) for t in tokens):
                data_line = line
                break
        if data_line is None:
            raise ELMError(f"PID {pid:#04x}: no hex response (got {raw_lines!r})")
        tokens = data_line.split()
        # Strip an optional ISO-TP header (first token) and the mode+PID echo.
        idx = 0
        if extended_header is not None and len(tokens) > 3:
            idx = 1  # skip header
        # tokens[idx] should be mode|0x40, tokens[idx+1] should be pid.
        body = tokens[idx + 2:]
        return [int(t, 16) for t in body]

    def read_pid(self, pid: int, **kw) -> Optional[int]:
        """Request a PID and return its value as a single integer.

        For multi-byte PIDs the bytes are combined big-endian.  Returns
        ``None`` when the adapter reports no data (all 0xFF).
        """
        data = self.request_pid(pid, **kw)
        if not data:
            return None
        value = 0
        for b in data:
            value = (value << 8) | b
        if value == 0xFFFF or all(b == 0xFF for b in data):
            return None
        return value
