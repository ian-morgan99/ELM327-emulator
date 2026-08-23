# Testing the AndrOBD Projects with the ELM327-emulator Test Harness

This repository ships an **`androbd_harness`** package that lets you test both
AndrOBD projects — **AndrOBD** (the Android OBD app) and
**AndrOBD-Plugin-Home-Assistant** (the HA publisher plugin) — without a car,
an ELM327 adapter, or even a real Home Assistant instance.

```
 +----------------+        +------------------+        +---------------+
 | ELM327-emulator| <----> | AndrobdSimulator | -----> | HaMockServer  |
 | (this repo)    |   TCP  | (stands in for  |  HTTP  | (stands in    |
 |                |        |  the Android    |        |  for Home     |
 |                |        |  app + HA plug) |        |  Assistant)   |
 +----------------+        +------------------+        +---------------+
```

Any component can be swapped for the real thing:

| Harness component | Stands in for            | Replace with                          |
|-------------------|--------------------------|---------------------------------------|
| `Elm` (emulator)  | ELM327 OBD-II adapter    | a real adapter / another emulator     |
| `AndrobdSimulator`| the AndrOBD Android app  | the real app on a phone (WiFi/serial) |
| `HaMockServer`    | Home Assistant           | a real HA instance (`--ha-url`)       |

The PID decode formulas in `androbd_harness/pids.py` are taken directly from
the AndrOBD source tree (`pids.csv` / `conversions.csv`), so values decoded by
the harness are **byte-for-byte identical** to what the real app hands to
plugins via `onDataUpdate(key, value)`.

---

## 1. Quick start: one command

From the repository root (Python 3.9+, no third-party deps needed for the
harness itself):

```bash
python -m androbd_harness.cli --duration 30
```

This starts the emulator, a mock Home Assistant, and a simulated drive cycle
(accelerate / cruise / traffic-light stops), polls PIDs every second, and
pushes them to the mock HA. After 30 s it prints a summary like:

```
=== harness summary ===
poll cycles completed : 30
HA posts sent         : 270 (errors: 0)
mock HA updates       : 270
  sensor.androbd_vehicle_speed = 9 (attrs={'friendly_name': 'vehicle_speed', ...})
  sensor.androbd_engine_speed = 1874 (...)
  ...
```

Useful options (see `python -m androbd_harness.cli --help` for all):

| Option | Default | Meaning |
|--------|---------|---------|
| `--elm-port` | `35000` | TCP port of the ELM327 emulator |
| `--scenario` | `car` | emulator scenario (`car`, `default`, ...) |
| `--duration` | `30` | seconds to run; `0` = until Ctrl-C |
| `--poll-interval` | `1.0` | AndrOBD poll interval (s) |
| `--drive-period` / `--max-speed` | `60` / `120` | drive-cycle oscillation period (s) and peak speed (km/h) |
| `--ha-port` | `0` (auto) | port of the mock HA server — **set a fixed port when testing the real plugin** |
| `--ha-token` | `test-ha-token` | bearer token for mock/real HA |
| `--no-mock-ha` + `--ha-url` | off | push to a *real* Home Assistant instead of the mock |
| `--entity-prefix` | `sensor.androbd_` | HA entity prefix (matches the plugin's default) |
| `--jsonl FILE` | off | mirror every HA update to a JSONL file for inspection |
| `--quiet` | off | only print the final summary |

---

## 2. Testing AndrOBD-Plugin-Home-Assistant

The plugin talks to Home Assistant with exactly two REST calls:

* `POST /api/states/<entity_id>` with a JSON body
  (`{"state": ..., "attributes": {...}}`) and an
  `Authorization: Bearer <token>` header,
* `GET /api/` as a liveness probe.

`HaMockServer` implements both (plus `GET /api/states/<entity_id>`) and
returns HTTP 401 for a wrong token — identical to real HA. So you can test
the plugin end-to-end with zero HA setup:

1. **Start the harness with a fixed HA port** so the plugin has a stable URL:

   ```bash
   python -m androbd_harness.cli --duration 0 \
       --ha-port 8123 --ha-token test-ha-token \
       --jsonl ha-updates.jsonl
   ```

   (`--duration 0` keeps it running until Ctrl-C.)

2. **Build and install the plugin** (in your AndrOBD-Plugin-Home-Assistant
   checkout):

   ```bash
   ./gradlew assembleDebug
   adb install -r src/build/outputs/apk/debug/*.apk
   ```

3. **Configure the plugin**: HA URL `http://<host-ip>:8123`, token
   `test-ha-token`. The host IP is the machine running the harness
   (`ip addr` on Linux, `ifconfig` on macOS). Phone and host must be on the
   same network; open the port in the host firewall if needed.

4. **Verify**: watch `ha-updates.jsonl` grow (one JSON object per update), or
   query the mock directly:

   ```bash
   curl http://127.0.0.1:8123/api/states/sensor.androbd_vehicle_speed
   ```

   The plugin creates entities under `sensor.androbd_<mnemonic>` (e.g.
   `sensor.androbd_vehicle_speed`, `sensor.androbd_engine_speed`,
   `sensor.androbd_odometer_reading`).

5. **Against a real HA** instead of the mock:

   ```bash
   python -m androbd_harness.cli --duration 0 \
       --no-mock-ha --ha-url http://homeassistant.local:8123 \
       --ha-token <long-lived-access-token>
   ```

   Then check *Developer Tools → States* in HA for the `sensor.androbd_*`
   entities.

### 2.1 Unit-testing the plugin's HTTP layer

For automated tests of the plugin (or any client of the HA API), start a mock
in-process and assert on what was received:

```python
from androbd_harness.ha_mock import HaMockServer

def test_plugin_posts_state():
    with HaMockServer(token="tok") as ha:
        # point your plugin under test at ha.url with token "tok" ...
        update = ha.wait_for_update("sensor.androbd_vehicle_speed", timeout=10)
        assert update is not None
        assert update["state"] == "9"

    # introspection helpers:
    #   ha.get_state(entity_id)  -> last state dict or None
    #   ha.updates_for(entity_id) -> chronological list of updates
    #   ha.auth_failures         -> count of 401s (wrong/missing token)
```

---

## 3. Testing the real AndrOBD app on a phone

The emulator speaks the ELM327 protocol over TCP, so the app sees it exactly
like a WiFi OBD adapter:

```bash
# keep the emulator + drive cycle running indefinitely
python -m androbd_harness.cli --duration 0 --elm-port 35000
```

On the phone: **AndrOBD → connection type "WiFi" → IP `<host-ip>`, port
`35000` → Connect**. You'll see live, changing values (speed oscillates, RPM
follows speed with gear steps, temperatures warm up, odometer integrates).

Combine both projects for a full end-to-end test: run the command above,
connect the phone with AndrOBD, enable the HA plugin in AndrOBD and point it
at the mock (`--ha-port`) or a real HA — the *real* app then drives the whole
pipeline.

If you only need the static scenario (no drive cycle), the plain emulator CLI
works too: `python -m elm -s car -n 35000`.

---

## 4. Using the harness in your own pytest suite

`tests/test_androbd_harness.py` in this repo is a working reference (29
tests, ~11 s). The key building blocks:

```python
import socket, time
from elm import Elm
from androbd_harness import (
    ELM327Client, AndrobdSimulator, HaMockServer, DrivingSimulator,
)

def _free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]; s.close()
    return port

def _connect_client(port, timeout=5.0):
    """The emulator's listener thread binds asynchronously - retry on OSError."""
    deadline = time.time() + timeout
    while True:
        try:
            return ELM327Client(port=port, timeout=timeout).connect()
        except OSError:
            if time.time() >= deadline:
                raise
            time.sleep(0.1)

def test_pipeline():
    port = _free_port()
    elm = Elm(net_port=port)
    elm.set_sorted_obd_msg("car")
    with elm:
        ha = HaMockServer(token="tok").start()
        try:
            sim = AndrobdSimulator(port=port, interval=0.2,
                                   ha_url=ha.url, ha_token="tok")
            for _ in range(20):                      # same bind race
                try:
                    sim.connect(); break
                except OSError:
                    time.sleep(0.1)
            snap = sim.poll_once()                  # one poll cycle (decode only)
            assert "vehicle_speed" in snap
            sim.push_to_ha(snap)                    # explicit HA push
            update = ha.wait_for_update("sensor.androbd_vehicle_speed")
            assert update is not None
        finally:
            sim.close(); ha.stop()
```

Run from the repository root so both `elm` and `androbd_harness` are
importable (the test suite does this; or set `PYTHONPATH=.`).

Notes that save real debugging time (all learned the hard way):

* **Connection race** — after `with elm:` starts, the listener thread may not
  have bound yet; always connect with a short retry loop.
* **`poll_once()` vs `run()`/`start()`** — `poll_once()` only polls and
  decodes; it does *not* push to HA. Call `sim.push_to_ha(snapshot)`
  explicitly, or use `sim.run(duration)` (blocking) / `sim.start()`
  (background thread at `interval`), which poll *and* push on every cycle.
* **`DrivingSimulator`** — feed the emulator live values:
  `drive = DrivingSimulator(max_speed=120, period=60)` then
  `drive.apply_to_emulator(elm, drive.step(0.5))` on a timer (or
  `drive.run(elm, interval=1.0, stop_event=evt)` in a thread).
* **`ELM327Client`** — for protocol-level tests: `.at("ATI")`,
  `.set_protocol(0)`, `.request_pid(0x0D)` (raw data bytes),
  `.read_pid(0x0C)` (decoded int, `None` on all-FF "no data").
* **PID math** — `decode_pid(pid, raw_bytes)`, `raw_for_value(pid, value)`,
  `format_value(pid, value)`; the all-`0xFF` pattern is the "N/A" sentinel.

Run the harness's own suite from the repo root:

```bash
python -m pytest tests/ -v        # 29 passed
```

---

## 5. Customising scenarios and PIDs

* **Scenarios** — `elm.set_sorted_obd_msg("car")` selects a scenario; any
  scenario name from the emulator's OBD message table works.
* **Per-PID overrides** — re-program individual answers at runtime (this is
  what `DrivingSimulator` does):

  ```python
  elm.answer["SPEED"] = ("<header>7E8</header><size>03</size>"
                         "<data>41 0D %02X</data>") % raw_speed
  ```

* **PID table** — `androbd_harness.pids.PID_TABLE` maps each PID to its
  AndrOBD mnemonic, decode formula (`fact`/`div`/`offs`), printf format, unit,
  byte count, and ISO-TP header (needed for extended PIDs like the odometer
  `0xA6`). `DEFAULT_PIDS` is the set the simulator polls.

---

## 6. Troubleshooting

| Symptom | Fix |
|---------|-----|
| `OSError: [Errno 111] Connection refused` right after starting the emulator | Listener thread not bound yet — retry the connect (see §4). |
| Phone can't reach the emulator | Same LAN? Host firewall open on the port? Use the host's LAN IP, not `127.0.0.1`. |
| Plugin gets HTTP 401 from HA/mock | Token mismatch — the mock enforces the exact `--ha-token` value. |
| Values stuck at scenario defaults | You're running plain `python -m elm` (static) — use the harness CLI or `DrivingSimulator` for live values. |
| A PID shows `N/A` | The adapter answered all-`0xFF` (the "no data" sentinel); check the scenario actually defines that PID. |
| Port already in use | Pick another `--elm-port` / `--ha-port`. |
