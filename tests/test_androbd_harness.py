#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for the androbd_harness package.

Run from the repository root::

    .venv/bin/python -m pytest tests/ -v

The unit tests (decode, entity ids, HA mock) are fast and dependency-free.
The integration test boots the real ELM327-emulator in-process on a free
port and drives the whole pipeline: emulator -> ELM327Client ->
AndrobdSimulator -> HaMockServer.
"""

import json
import socket
import threading
import time
import urllib.error
import urllib.request

import pytest

from androbd_harness.androbd_sim import AndrobdSimulator, build_entity_id
from androbd_harness.driving import DrivingSimulator
from androbd_harness.elm_client import ELM327Client, ELMError
from androbd_harness.ha_mock import HaMockServer
from androbd_harness.pids import (
    DEFAULT_PIDS,
    PID_TABLE,
    decode_pid,
    format_value,
    raw_bytes_for_value,
    raw_for_value,
)


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _connect_client(port: int, timeout: float = 5.0) -> ELM327Client:
    """Connect with retries - the emulator's listener thread may need a
    moment to bind after ``with elm:`` starts it."""
    deadline = time.time() + timeout
    last_exc = None
    while time.time() < deadline:
        try:
            return ELM327Client(port=port, timeout=timeout).connect()
        except OSError as exc:
            last_exc = exc
            time.sleep(0.1)
    raise last_exc


# --------------------------------------------------------------------------- #
# pids.py - decode formulas (must match AndrOBD's conversions.csv exactly)
# --------------------------------------------------------------------------- #
class TestPids:
    def test_speed_identity(self):
        assert decode_pid(0x0D, [99]) == 99.0

    def test_rpm_quarter_division(self):
        # AndrOBD: RPM = raw / 4
        assert decode_pid(0x0C, [0x09, 0xB0]) == 0x09B0 / 4.0

    def test_temperature_offset_minus_40(self):
        # AndrOBD uses offset -40 (not the spec's -48)
        assert decode_pid(0x05, [70]) == 30.0
        assert decode_pid(0x0F, [68]) == 28.0

    def test_voltage_div_1000(self):
        # AndrOBD: V = raw / 1000 (not the spec's /16)
        assert decode_pid(0x42, [0x36, 0xB9]) == 0x36B9 / 1000.0

    def test_maf_div_100(self):
        # AndrOBD: g/s = raw / 100 (not the spec's /4.096)
        assert decode_pid(0x10, [0x03, 0xE8]) == 10.0  # 0x03E8 = 1000

    def test_percent_scaling(self):
        assert decode_pid(0x04, [0xFF]) is None  # all-FF = not available
        assert decode_pid(0x11, [0x7F]) == pytest.approx(100.0 * 0x7F / 255.0)

    def test_odometer_div_10(self):
        assert decode_pid(0xA6, [0x00, 0xEA, 0x60, 0x00]) == 0xEA6000 / 10.0

    def test_all_ff_is_na(self):
        for pid in DEFAULT_PIDS:
            nbytes = PID_TABLE[pid]["nbytes"]
            assert decode_pid(pid, [0xFF] * nbytes) is None

    def test_format_value_matches_androbd_printf(self):
        assert format_value(0x0D, 99.0) == "99"          # %.0f
        assert format_value(0x42, 13.821) == "13.821"    # %.3f
        assert format_value(0x10, 123.456) == "123.46"   # %.2f
        assert format_value(0x0D, None) == "N/A"

    def test_raw_for_value_round_trip(self):
        # Encoding a physical value and decoding the resulting bytes must
        # yield (approximately) the same value for every default PID.
        for pid in DEFAULT_PIDS:
            nbytes = PID_TABLE[pid]["nbytes"]
            spec = PID_TABLE[pid]
            # A mid-range physical value, well inside the raw range.
            value = ((1 << (8 * nbytes)) - 2) * spec["fact"] / spec["div"] / 3.0
            raw = raw_for_value(pid, value)
            assert 0 <= raw < (1 << (8 * nbytes))
            decoded = decode_pid(pid, raw_bytes_for_value(pid, value))
            assert decoded is not None
            assert abs(decoded - value) < spec["fact"] / spec["div"] + 1e-9

    def test_every_default_pid_has_scenario_key(self):
        for pid in DEFAULT_PIDS:
            spec = PID_TABLE[pid]
            assert spec["scenario"], f"PID {pid:#04x} missing scenario key"


# --------------------------------------------------------------------------- #
# androbd_sim.py - entity id construction (must match the HA plugin)
# --------------------------------------------------------------------------- #
class TestEntityId:
    def test_plain_mnemonic(self):
        assert build_entity_id("vehicle_speed") == "sensor.androbd_vehicle_speed"

    def test_dashes_become_underscores(self):
        assert build_entity_id("engine-load") == "sensor.androbd_engine_load"

    def test_consecutive_underscores_collapsed(self):
        assert build_entity_id("a__b") == "sensor.androbd_a_b"

    def test_uppercase_lowered(self):
        assert build_entity_id("RPM") == "sensor.androbd_rpm"

    def test_custom_prefix(self):
        assert build_entity_id("speed", "sensor.car_") == "sensor.car_speed"


# --------------------------------------------------------------------------- #
# ha_mock.py - mock Home Assistant server
# --------------------------------------------------------------------------- #
class TestHaMock:
    @pytest.fixture()
    def ha(self):
        server = HaMockServer(token="sekret").start()
        yield server
        server.stop()

    def _post(self, ha, entity, state, token="sekret"):
        url = f"{ha.url}/api/states/{entity}"
        body = json.dumps({"state": state, "attributes": {}}).encode()
        req = urllib.request.Request(url, data=body, method="POST")
        req.add_header("Content-Type", "application/json")
        if token is not None:
            req.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status
        except urllib.error.HTTPError as e:
            return e.code

    def test_post_and_get_state(self, ha):
        assert self._post(ha, "sensor.androbd_vehicle_speed", "87") == 200
        st = ha.get_state("sensor.androbd_vehicle_speed")
        assert st is not None and st["state"] == "87"

    def test_updates_recorded(self, ha):
        self._post(ha, "sensor.x", "1")
        self._post(ha, "sensor.x", "2")
        assert len(ha.updates_for("sensor.x")) == 2

    def test_wrong_token_401(self, ha):
        assert self._post(ha, "sensor.x", "1", token="wrong") == 401
        assert ha.auth_failures >= 1

    def test_no_token_required_when_unset(self):
        with HaMockServer() as anon:
            assert self._post(anon, "sensor.y", "5", token=None) == 200

    def test_wait_for_update(self, ha):
        def push():
            time.sleep(0.2)
            self._post(ha, "sensor.z", "42")
        threading.Thread(target=push, daemon=True).start()
        upd = ha.wait_for_update("sensor.z", timeout=5)
        assert upd is not None and upd["state"] == "42"

    def test_jsonl_mirror(self, tmp_path):
        path = tmp_path / "updates.jsonl"
        with HaMockServer(jsonl_path=str(path)) as ha:
            self._post(ha, "sensor.j", "9")
        lines = path.read_text().strip().splitlines()
        assert len(lines) == 1
        assert json.loads(lines[0])["entity"] == "sensor.j"


# --------------------------------------------------------------------------- #
# driving.py - drive cycle model
# --------------------------------------------------------------------------- #
class TestDriving:
    def test_step_returns_all_mnemonics(self):
        d = DrivingSimulator(seed=1)
        vals = d.step(1.0)
        for pid in DEFAULT_PIDS:
            assert PID_TABLE[pid]["mnemonic"] in vals

    def test_speed_stays_in_bounds(self):
        d = DrivingSimulator(max_speed=80, seed=2)
        for _ in range(50):
            v = d.step(1.0)["vehicle_speed"]
            assert 0.0 <= v <= 80.0

    def test_odometer_increases_with_speed(self):
        d = DrivingSimulator(seed=3)
        before = d.odometer_km
        for _ in range(10):
            d.step(1.0)
        assert d.odometer_km > before

    def test_throttle_never_hits_ff_sentinel(self):
        d = DrivingSimulator(max_speed=200, seed=4)
        for _ in range(200):
            v = d.step(0.5)["throttle_position_abs"]
            assert raw_for_value(0x11, v) != 0xFF


# --------------------------------------------------------------------------- #
# Integration: full pipeline emulator -> client -> sim -> mock HA
# --------------------------------------------------------------------------- #
class TestFullPipeline:
    def test_end_to_end(self):
        from elm.elm import Elm

        port = _free_port()
        elm = Elm(net_port=port)
        with elm:
            elm.set_sorted_obd_msg("car")

            ha = HaMockServer(token="tok").start()
            drive = DrivingSimulator(max_speed=100, period=30, seed=7)
            drive.apply_to_emulator(elm, drive.step(0.0))

            stop_evt = threading.Event()
            drive_thread = threading.Thread(
                target=drive.run,
                kwargs={"elm": elm, "interval": 0.5, "stop_event": stop_evt},
                daemon=True)
            drive_thread.start()

            sim = AndrobdSimulator(port=port, interval=0.5, ha_url=ha.url,
                                   ha_token="tok")
            # The emulator's listener thread may need a moment to bind.
            for _ in range(20):
                try:
                    sim.connect()
                    break
                except OSError:
                    time.sleep(0.1)
            t0 = time.time()
            while time.time() - t0 < 3.0:
                sim.poll_once()
                sim.push_to_ha(sim.last_values)
                time.sleep(0.5)

            stop_evt.set()
            drive_thread.join(timeout=3)
            sim.close()
            ha.stop()

        # Every default PID produced at least one HA update with the right id.
        for pid in DEFAULT_PIDS:
            entity = build_entity_id(PID_TABLE[pid]["mnemonic"])
            assert ha.get_state(entity) is not None, f"no updates for {entity}"

        # Values actually changed over time (drive cycle is live).
        speed_updates = [u["state"] for u in ha.updates_for(
            build_entity_id("vehicle_speed"))]
        assert len(set(speed_updates)) > 1, "speed never changed"

        # The plugin's attribute contract is preserved.
        st = ha.get_state(build_entity_id("ecu_voltage"))
        assert st["attributes"]["source"] == "AndrOBD"
        assert st["attributes"]["friendly_name"] == "ecu_voltage"
        assert isinstance(st["attributes"]["timestamp"], int)

    def test_client_at_commands_and_pid(self):
        from elm.elm import Elm

        port = _free_port()
        elm = Elm(net_port=port)
        with elm:
            elm.set_sorted_obd_msg("car")
            c = _connect_client(port)
            try:
                assert "ELM327" in c.at("ATI")
                assert c.at("ATL1") == "OK"
                # Scenario default for SPEED is 0x0A (10 km/h)
                assert c.request_pid(0x0D) == [0x0A]
                # Dynamic override must be visible to the client
                elm.answer["SPEED"] = (
                    "<header>7E8</header><size>03</size>"
                    "<data>41 0D 63</data>")
                assert c.request_pid(0x0D) == [0x63]
            finally:
                c.close()

    def test_client_no_response_raises(self):
        # A server that accepts and immediately closes must make at() raise
        # ELMError (no response), not hang forever.
        port = _free_port()
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(("127.0.0.1", port))
        listener.listen(1)
        listener.settimeout(5)

        c = ELM327Client(port=port, timeout=1.0).connect()
        conn, _ = listener.accept()
        conn.close()
        listener.close()
        try:
            with pytest.raises(ELMError):
                c.at("ATZ", expect="OK")
        finally:
            c.close()
