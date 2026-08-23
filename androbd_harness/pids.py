#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PID decode table for the AndrOBD test harness.

The formulas and formats below are taken *directly* from the AndrOBD source
tree so that values decoded here are identical to what the real app would
compute and hand to plugins (``onDataUpdate(key, value)``):

  * ``library/src/main/java/com/fr3ts0n/ecu/prot/obd/res/pids.csv``
      - column 8: conversion id (e.g. ``VEHSPEED``, ``RPM``)
      - column 9: printf format (e.g. ``%.0f``)
      - column 13: mnemonic (the ``key`` passed to plugins)
  * ``library/src/main/java/com/fr3ts0n/ecu/prot/obd/res/conversions.csv``
      - LINEAR conversions: ``value = raw * FACT / DIV + OFFS`` (metric)

Note that AndrOBD's factors differ from the generic OBD-II spec in a few
places (e.g. voltage is ``raw/1000`` V, temperature offset is -40 C, MAF is
``raw/100`` g/s).  We follow AndrOBD, because that is what the Home
Assistant plugin will actually receive.

Each table entry:
    pid (int) -> {
        'mnemonic':  key used by AndrOBD / HA plugin,
        'label':     human readable name,
        'fact':      linear factor,
        'div':       linear divisor,
        'offs':      offset,
        'fmt':       printf format string,
        'unit':      display unit,
        'nbytes':    number of data bytes in the OBD response,
        'header':    ISO-TP header needed to request it (None = standard),
        'scenario':  key of this PID in the emulator's 'car' scenario
                     (used to override responses via ``elm.answer``),
    }
"""

from __future__ import annotations

from typing import Dict, List, Optional

# --------------------------------------------------------------------------- #
# PID table (metric system, as configured by default in AndrOBD)
# --------------------------------------------------------------------------- #
PID_TABLE: Dict[int, dict] = {
    0x04: {
        "mnemonic": "engine_load_calculated",
        "label": "Calculated Engine Load",
        "fact": 100.0, "div": 255.0, "offs": 0.0,
        "fmt": "%.1f", "unit": "%", "nbytes": 1, "header": None,
        "scenario": "ENGINE_LOAD",
    },
    0x05: {
        "mnemonic": "engine_coolant_temperature",
        "label": "Engine Coolant Temperature",
        "fact": 1.0, "div": 1.0, "offs": -40.0,
        "fmt": "%.1f", "unit": "\u00b0C", "nbytes": 1, "header": None,
        "scenario": "COOLANT_TEMP",
    },
    0x0C: {
        "mnemonic": "engine_speed",
        "label": "Engine Speed",
        "fact": 1.0, "div": 4.0, "offs": 0.0,
        "fmt": "%.0f", "unit": "/min", "nbytes": 2, "header": None,
        "scenario": "RPM",
    },
    0x0D: {
        "mnemonic": "vehicle_speed",
        "label": "Vehicle Speed",
        "fact": 1.0, "div": 1.0, "offs": 0.0,
        "fmt": "%.0f", "unit": "km/h", "nbytes": 1, "header": None,
        "scenario": "SPEED",
    },
    0x0F: {
        "mnemonic": "intake_air_temperature",
        "label": "Intake Air Temperature",
        "fact": 1.0, "div": 1.0, "offs": -40.0,
        "fmt": "%.1f", "unit": "\u00b0C", "nbytes": 1, "header": None,
        "scenario": "INTAKE_TEMP",
    },
    0x10: {
        "mnemonic": "mass_airflow",
        "label": "Mass Air Flow",
        "fact": 1.0, "div": 100.0, "offs": 0.0,
        "fmt": "%.2f", "unit": "g/s", "nbytes": 2, "header": None,
        "scenario": "MAF",
    },
    0x11: {
        "mnemonic": "throttle_position_abs",
        "label": "Throttle Position",
        "fact": 100.0, "div": 255.0, "offs": 0.0,
        "fmt": "%.1f", "unit": "%", "nbytes": 1, "header": None,
        "scenario": "THROTTLE_POS",
    },
    0x21: {
        "mnemonic": "distance_sine_mil_active",
        "label": "Distance Since MIL Active",
        "fact": 1.0, "div": 1.0, "offs": 0.0,
        "fmt": "%.0f", "unit": "km", "nbytes": 2, "header": None,
        "scenario": "DISTANCE_W_MIL",
    },
    0x42: {
        "mnemonic": "ecu_voltage",
        "label": "Control Module Voltage",
        "fact": 1.0, "div": 1000.0, "offs": 0.0,
        "fmt": "%.3f", "unit": "V", "nbytes": 2, "header": None,
        "scenario": "CONTROL_MODULE_VOLTAGE",
    },
    0xA6: {
        "mnemonic": "odometer_reading",
        "label": "Odometer Reading",
        "fact": 1.0, "div": 10.0, "offs": 0.0,
        "fmt": "%.1f", "unit": "km", "nbytes": 4, "header": None,
        "scenario": "ODOMETER",
    },
}

# PIDs the harness simulates by default (the ones the HA plugin cares about).
DEFAULT_PIDS = [0x0D, 0x0C, 0x04, 0x05, 0x0F, 0x10, 0x11, 0x42, 0xA6]


def decode_pid(pid: int, raw_bytes: List[int]) -> Optional[float]:
    """Decode raw OBD data bytes into a physical value using AndrOBD's formula.

    Returns ``None`` when the PID is unknown or the data is all-0xFF
    (not supported).
    """
    spec = PID_TABLE.get(pid)
    if spec is None:
        return None
    raw = 0
    for b in raw_bytes:
        raw = (raw << 8) | b
    if len(raw_bytes) and all(b == 0xFF for b in raw_bytes):
        return None
    return raw * spec["fact"] / spec["div"] + spec["offs"]


def format_value(pid: int, value: Optional[float]) -> str:
    """Format a decoded value exactly like AndrOBD does (its printf format)."""
    if value is None:
        return "N/A"
    spec = PID_TABLE.get(pid)
    fmt = spec["fmt"] if spec else "%.1f"
    try:
        return fmt % value
    except (TypeError, ValueError):
        return str(value)


def raw_for_value(pid: int, value: float) -> int:
    """Inverse of :func:`decode_pid` - compute the raw OBD value that would
    decode to ``value``.  Used by the driving simulator to program the
    emulator with realistic raw bytes."""
    spec = PID_TABLE[pid]
    raw = (value - spec["offs"]) * spec["div"] / spec["fact"]
    nbytes = spec["nbytes"]
    lo, hi = 0, (1 << (8 * nbytes)) - 1
    return max(lo, min(hi, int(round(raw))))


def raw_bytes_for_value(pid: int, value: float) -> List[int]:
    """Raw big-endian byte sequence for a physical value."""
    spec = PID_TABLE[pid]
    raw = raw_for_value(pid, value)
    nbytes = spec["nbytes"]
    return [(raw >> (8 * (nbytes - 1 - i))) & 0xFF for i in range(nbytes)]
