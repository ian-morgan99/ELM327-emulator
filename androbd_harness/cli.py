#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
One-command orchestration of the full AndrOBD / Home Assistant test pipeline.

    +----------------+        +------------------+        +---------------+
    | ELM327-emulator| <----> | AndrobdSimulator | -----> | HaMockServer  |
    | (this repo)    |   TCP  | (stands in for  |  HTTP  | (stands in    |
    |                |        |  the Android    |        |  for Home     |
    |                |        |  app + HA plug) |        |  Assistant)   |
    +----------------+        +------------------+        +---------------+

Usage examples
--------------
Run everything in-process (emulator + simulator + mock HA) for 30 seconds::

    python -m androbd_harness.cli --duration 30

Point the simulator at a *real* Home Assistant instance instead of the mock::

    python -m androbd_harness.cli --no-mock-ha \
        --ha-url http://homeassistant.local:8123 --ha-token <long-lived-token>

Leave the emulator running so a real phone (AndrOBD app) can connect to it,
while the simulator keeps feeding it a live drive cycle::

    python -m androbd_harness.cli --duration 0 --elm-port 35000

Then on the phone: AndrOBD -> connection type "WiFi" -> IP ``<this-host>``
port ``35000``.  The HA plugin (or the simulator) will see live data.
"""

from __future__ import annotations

import argparse
import signal
import sys
import time
from typing import List, Optional


def _pick_free_port() -> int:
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="androbd_harness",
        description="End-to-end test harness for the AndrOBD + Home "
                    "Assistant integration, built on the ELM327-emulator.")
    p.add_argument("--elm-port", type=int, default=35000,
                   help="TCP port for the ELM327 emulator (default 35000)")
    p.add_argument("--scenario", default="car",
                   help="emulator scenario (default 'car')")
    p.add_argument("--duration", type=float, default=30.0,
                   help="seconds to run; 0 = run until Ctrl-C (default 30)")
    p.add_argument("--poll-interval", type=float, default=1.0,
                   help="AndrOBD poll interval in seconds (default 1.0)")
    p.add_argument("--drive-period", type=float, default=60.0,
                   help="drive-cycle oscillation period in seconds")
    p.add_argument("--max-speed", type=float, default=120.0,
                   help="peak speed of the drive cycle in km/h")
    p.add_argument("--ha-port", type=int, default=0,
                   help="port for the mock Home Assistant server "
                        "(0 = pick a free port)")
    p.add_argument("--ha-token", default="test-ha-token",
                   help="bearer token for the mock/real HA (default test-ha-token)")
    p.add_argument("--no-mock-ha", action="store_true",
                   help="do not start the mock HA server")
    p.add_argument("--ha-url", default=None,
                   help="push to this real HA URL instead of the mock "
                        "(e.g. http://192.168.1.50:8123)")
    p.add_argument("--entity-prefix", default="sensor.androbd_",
                   help="HA entity prefix (default sensor.androbd_)")
    p.add_argument("--jsonl", default=None,
                   help="also append every HA update to this JSONL file")
    p.add_argument("--quiet", action="store_true",
                   help="only print the final summary")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    # ------------------------------------------------------------------ #
    # 1. ELM327 emulator (in-process, TCP server mode)
    # ------------------------------------------------------------------ #
    from elm import Elm
    from androbd_harness.driving import DrivingSimulator
    from androbd_harness.ha_mock import HaMockServer
    from androbd_harness.androbd_sim import AndrobdSimulator

    elm = Elm(net_port=args.elm_port)
    elm.set_sorted_obd_msg(args.scenario)
    with elm:
        if not args.quiet:
            print(f"[harness] ELM327-emulator listening on "
                  f"tcp://127.0.0.1:{args.elm_port} (scenario={args.scenario!r})")

        # ------------------------------------------------------------------ #
        # 2. Mock Home Assistant server
        # ------------------------------------------------------------------ #
        ha = None
        if not args.no_mock_ha and not args.ha_url:
            ha = HaMockServer(port=args.ha_port, token=args.ha_token,
                              jsonl_path=args.jsonl).start()
            if not args.quiet:
                print(f"[harness] mock Home Assistant at {ha.url} "
                      f"(token={args.ha_token!r})")

        ha_url = args.ha_url or (ha.url if ha else None)

        # ------------------------------------------------------------------ #
        # 3. Driving simulator -> feeds the emulator's answer templates
        # ------------------------------------------------------------------ #
        drive = DrivingSimulator(max_speed=args.max_speed,
                                 period=args.drive_period)
        import threading as _th
        stop_evt = _th.Event()
        drive_thread = _th.Thread(
            target=drive.run,
            kwargs={"elm": elm, "interval": args.poll_interval,
                    "stop_event": stop_evt},
            daemon=True)

        # ------------------------------------------------------------------ #
        # 4. AndrOBD simulator -> polls the emulator, pushes to HA
        # ------------------------------------------------------------------ #
        sim = AndrobdSimulator(host="127.0.0.1", port=args.elm_port,
                               interval=args.poll_interval,
                               ha_url=ha_url, ha_token=args.ha_token,
                               entity_prefix=args.entity_prefix)

        ticks: List[dict] = []

        def _on_update(snapshot):
            ticks.append(snapshot)
            if not args.quiet:
                print("  " + "  ".join(f"{k}={v}" for k, v in snapshot.items()))

        sim.on_update = _on_update

        # Seed the emulator with an initial telemetry snapshot so the very
        # first poll cycle (which can run before the drive thread's first
        # tick) already sees live values instead of scenario defaults.
        drive.apply_to_emulator(elm, drive.step(0.0))

        stop_evt.clear()
        drive_thread.start()
        sim.connect()
        sim.start(push_to_ha=ha_url is not None)

        if not args.quiet:
            print(f"[harness] running for "
                  f"{'infinity (Ctrl-C)' if args.duration <= 0 else args.duration:.0f}s ...")

        # ------------------------------------------------------------------ #
        # 5. Run until duration elapses or Ctrl-C
        # ------------------------------------------------------------------ #
        def _sigint(_signum, _frame):
            stop_evt.set()
            sim.stop()
        signal.signal(signal.SIGINT, _sigint)

        try:
            if args.duration > 0:
                time.sleep(args.duration)
            else:
                while not stop_evt.is_set():
                    time.sleep(0.5)
        finally:
            stop_evt.set()
            sim.stop()
            sim.close()
            drive_thread.join(timeout=3)

        # ------------------------------------------------------------------ #
        # 6. Summary
        # ------------------------------------------------------------------ #
        print("\n=== harness summary ===")
        print(f"poll cycles completed : {sim.poll_count}")
        print(f"HA posts sent         : {sim.ha_posts} (errors: {sim.ha_errors})")
        if ha is not None:
            print(f"mock HA updates       : {len(ha.updates)}")
            for entity in sorted(ha.states):
                st = ha.states[entity]
                print(f"  {entity} = {st['state']} "
                      f"(attrs={st['attributes']})")
        if sim.last_values:
            print("last decoded values :")
            for k, v in sim.last_values.items():
                print(f"  {k} = {v}")
        if ha is not None:
            ha.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
