#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Driving simulator.

Generates a realistic, time-varying "drive cycle" (accelerate, cruise,
decelerate, stop) and pushes the resulting telemetry into the ELM327-emulator
via its ``answer`` override mechanism, so that any client connected to the
emulator (the real AndrOBD app on a phone, or :class:`AndrobdSimulator`)
sees live-changing values.

The simulator works by re-programming the emulator's response templates on a
timer:

    e.answer['SPEED'] = ('<header>7E8</header><size>03</size>'
                        '<data>41 0D %02X</data>') % raw_speed

``raw_speed`` is computed from the physical value using the *inverse* of
AndrOBD's decode formula (see :mod:`pids`), so the round-trip
(simulate -> ELM327 wire -> AndrOBD decode) yields exactly the value the
drive cycle produced.

Drive cycle
-----------
A smooth composite of a slow sine wave (cruise oscillation) plus occasional
"traffic light" stops, clamped to 0..max_speed.  Engine RPM follows speed
with a gear-like step function plus idle offset; throttle and load follow
the acceleration; coolant/intake temperatures warm up over time; the
odometer integrates speed; battery voltage sags under load.
"""

from __future__ import annotations

import math
import random
import threading
import time
from typing import Callable, Dict, List, Optional

from .pids import PID_TABLE, raw_for_value


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


class DrivingSimulator:
    """Time-varying vehicle telemetry source.

    Parameters
    ----------
    max_speed :
        Peak speed of the drive cycle in km/h (default 120).
    period :
        Period of the main speed oscillation in seconds (default 60).
    stop_probability :
        Probability per tick that the car "hits a traffic light" and brakes
        to a stop for a few seconds (default 0.05).
    """

    def __init__(self, max_speed: float = 120.0, period: float = 60.0,
                 stop_probability: float = 0.05, seed: Optional[int] = None):
        self.max_speed = max_speed
        self.period = period
        self.stop_probability = stop_probability
        self._rng = random.Random(seed)
        self.t0 = time.time()
        self._stop_until = 0.0
        # Odometer state (km)
        self.odometer_km = 42137.5
        # Warm-up state
        self.coolant_temp = 25.0
        self.intake_temp = 28.0

    # ------------------------------------------------------------------ #
    # Drive cycle model
    # ------------------------------------------------------------------ #
    def step(self, dt: float) -> Dict[str, float]:
        """Advance the simulation by ``dt`` seconds and return a dict of
        physical values keyed by AndrOBD mnemonic."""
        t = time.time() - self.t0

        # --- speed ----------------------------------------------------- #
        if t < self._stop_until:
            target_speed = 0.0
        else:
            wave = 0.5 + 0.5 * math.sin(2.0 * math.pi * t / self.period)
            target_speed = self.max_speed * (0.15 + 0.85 * wave)
            if self._rng.random() < self.stop_probability:
                self._stop_until = t + self._rng.uniform(3.0, 8.0)

        # Smoothly approach the target (simple first-order lag).
        prev_speed = getattr(self, "_last_speed", 0.0)
        speed = prev_speed + (target_speed - prev_speed) * min(1.0, dt * 0.8)
        speed = _clamp(speed, 0.0, self.max_speed)
        self._last_speed = speed

        # --- engine speed (gear-like steps) ---------------------------- #
        if speed < 1.0:
            rpm = 750.0 + 60.0 * math.sin(t * 2.0)  # idle wobble
        else:
            gear = min(6, int(speed / 25) + 1)
            base_rpm = 1800.0 + (gear - 1) * 900.0
            rpm = _clamp(base_rpm + speed * 8.0, 1500.0, 6500.0)

        # --- throttle & load from acceleration ------------------------- #
        # Capped at 99%: a raw value of 0xFF (100%) is the OBD "not
        # available" sentinel, which AndrOBD would render as N/A.
        accel = (speed - prev_speed) / max(dt, 1e-3)  # km/h per s
        throttle = _clamp(8.0 + accel * 22.0, 0.0, 99.0)
        load = _clamp(throttle * 0.9 + 5.0, 0.0, 100.0)

        # --- temperatures (warm-up curves) ----------------------------- #
        self.coolant_temp += (90.0 - self.coolant_temp) * min(1.0, dt / 300.0)
        self.intake_temp += (45.0 - self.intake_temp) * min(1.0, dt / 240.0)

        # --- mass airflow follows speed -------------------------------- #
        maf = _clamp(speed * 1.6 + 8.0, 0.0, 900.0)

        # --- battery voltage sags under load --------------------------- #
        voltage = 13.9 - (load / 100.0) * 0.5 + 0.05 * math.sin(t * 0.7)

        # --- odometer integration -------------------------------------- #
        self.odometer_km += speed * dt / 3600.0

        return {
            "vehicle_speed": speed,
            "engine_speed": rpm,
            "engine_load_calculated": load,
            "throttle_position_abs": throttle,
            "engine_coolant_temperature": self.coolant_temp,
            "intake_air_temperature": self.intake_temp,
            "mass_airflow": maf,
            "ecu_voltage": voltage,
            "odometer_reading": self.odometer_km,
        }

    # ------------------------------------------------------------------ #
    # Emulator integration
    # ------------------------------------------------------------------ #
    def apply_to_emulator(self, elm, values: Optional[Dict[str, float]] = None):
        """Program ``elm.answer`` templates so the next client requests see
        these values.  ``elm`` is an :class:`elm.elm.Elm` instance (or any
        object exposing an ``answer`` dict)."""
        if values is None:
            values = self.step(0.0)
        for pid, spec in PID_TABLE.items():
            mnemonic = spec["mnemonic"]
            if mnemonic not in values:
                continue
            raw = raw_for_value(pid, values[mnemonic])
            nbytes = spec["nbytes"]
            data_bytes = " ".join(
                "%02X" % ((raw >> (8 * (nbytes - 1 - i))) & 0xFF)
                for i in range(nbytes))
            # Response: [header] [size] [data]; size == TOTAL byte count of
            # the data field (the "41 XX" mode/PID prefix + nbytes payload).
            header = spec["header"] if spec["header"] is not None else 0x7E8
            mode_pid = "41 %02X" % pid
            total_bytes = 2 + nbytes
            template = (f"<header>{header:02X}</header>"
                        f"<size>{total_bytes:02X}</size>"
                        f"<data>{mode_pid} {data_bytes}</data>")
            # The emulator's answer dict is keyed by *scenario* key
            # (SPEED, RPM, ODOMETER, ...) - see elm/obd_message.py.
            elm.answer[spec["scenario"]] = template

    def run(self, elm, interval: float = 1.0,
            duration: Optional[float] = None,
            on_tick: Optional[Callable[[Dict[str, float]], None]] = None,
            stop_event: Optional[threading.Event] = None):
        """Blocking loop that keeps the emulator fed with fresh telemetry.

        Returns a list of the value dicts produced (useful for tests).
        """
        history: List[Dict[str, float]] = []
        start = time.time()
        while True:
            if stop_event is not None and stop_event.is_set():
                break
            if duration is not None and time.time() - start >= duration:
                break
            values = self.step(interval)
            try:
                self.apply_to_emulator(elm, values)
            except Exception:  # emulator gone - stop quietly
                break
            history.append(values)
            if on_tick is not None:
                on_tick(values)
            time.sleep(interval)
        return history
