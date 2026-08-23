#!/usr/bin/env python3
# -*- coding: utf-8 -*-
###########################################################################
# AndrOBD / Home Assistant test harness for the ELM327-emulator.
#
# Simulates the full pipeline used by the two AndrOBD projects:
#
#   [ELM327-emulator]  <--TCP/serial-->  [AndrOBD app]  -->  [Home Assistant]
#        (this repo)                        (Android)         (HA plugin)
#
# This package provides:
#   * ELM327Client      - a faithful ELM327 protocol client (AT + OBD PIDs)
#   * DrivingSimulator  - generates realistic, time-varying vehicle telemetry
#   * HaMockServer      - a mock of the Home Assistant REST API used by the
#                         AndrOBD-Plugin-Home-Assistant project
#   * AndrobdSimulator  - emulates the AndrOBD app: polls PIDs from the
#                         emulator, decodes them exactly like the real app,
#                         and pushes values to Home Assistant (mock or real)
#   * cli               - one-command orchestration of the whole pipeline
###########################################################################

__version__ = "1.0.0"

from .elm_client import ELM327Client, ELMError
from .pids import PID_TABLE, decode_pid, format_value
from .driving import DrivingSimulator
from .ha_mock import HaMockServer
from .androbd_sim import AndrobdSimulator

__all__ = [
    "ELM327Client", "ELMError",
    "PID_TABLE", "decode_pid", "format_value",
    "DrivingSimulator",
    "HaMockServer",
    "AndrobdSimulator",
]
