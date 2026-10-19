# CAVIA Laptop Runtime

Laptop-side software for MyoGrip CAVIA (Context-Aware Visual Intent Arbitration).

| Package | Status | Contents |
|---|---|---|
| `core/` | ✅ | Message contracts, grip library, config, event bus |
| `fsm/` | ✅ | Python reference FSM (mirror of the firmware FSM) + simulator window |
| `emg/` | ◐ | WASDE keyboard EMG emulator (gesture detector and CSV replay to come) |
| `vision/` | ◐ | Camera source, YOLO detection, reticle, regions, tracker (standalone script; packaging pending) |
| `arbitration/`, `runtime/`, `dashboard/`, `eval/` | ☐ | Planned — see [`docs/architecture.md`](../../docs/architecture.md) |

## Setup

From the repository root:

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"            # core + FSM + tests (light)
pip install -e ".[sim,dev]"        # add the FSM simulator window (pygame-ce)
pip install -e ".[vision,dev]"     # add camera + YOLO stack (heavy)
```

`pyproject.toml` declares the package and its optional dependency groups.
`vision/requirements.txt` is a pinned freeze for reproducing the exact vision environment:
`pip install -r src/cavia/vision/requirements.txt`.

## FSM simulator (no hardware)

```bash
pytest
python -m cavia.fsm.sim --menu LATERAL,PINCH
python -m cavia.fsm.sim --menu LATERAL --policy ONE_CONFIRM
python -m cavia.fsm.sim --menu POWER,PINCH,TRIPOD,LATERAL --policy FULL_MENU   # manual cycling
```

Opens a window showing the vertical menu, FSM state, grip progress bar, held keys and an event log.

| Key | Menu mode | Actuation mode |
|---|---|---|
| `W` | SE — move up | — |
| `S` | SF — move down | — |
| `A` | LF — confirm selected grip (keep holding to start closing) | **hold** = flexor active → close; release → hold |
| `D` | LE — open Full Menu | **hold** = extensor active → open; stops at fully open (grip stays active) |
| `E` | HE — back to CAVIA Home | HE — the only way out of a grip: controlled opening, then Full Menu |
| `M` | reload mock menu (HOME only) | — |
| `Q` / `Esc` | quit | quit |

Rules mirroring real EMG:
- One press = one gesture; holding `W`/`S` moves only once (no auto-repeat).
- One press of `A` confirms **and** starts closing: keep holding to close, release to hold.
  A quick tap confirms without moving the hand.
- Close/open as many times as needed with the same grip; reaching fully open does not leave the grip.
- A gesture key pressed while another gesture key is held is ambiguous → `INVALID` (no action).
  Release `A` before pressing `E` to go back.
- `A` + `D` held together = co-contraction → hand stops and waits for full release.
- If the window loses focus, all keys are treated as released (the hand holds).
- A stalled window (e.g. while dragging) advances the hand by at most 0.1 s worth of movement.

## Vision pipeline

### Camera configuration

Copy the example and edit it:

```bash
cp src/cavia/vision/.env.example src/cavia/vision/.env
```

| Variable | Default | Meaning |
|---|---|---|
| `CAVIA_CAMERA_IP` | — | XIAO IP or hostname only (no `http://`, no port). Required unless `CAMERA_MODE=laptop` |
| `CAVIA_CAMERA_PORT` | `81` | XIAO MJPEG port (stream path is `/stream`) |
| `CAMERA_MODE` | `auto` | `auto`, `xiao` or `laptop` |
| `LAPTOP_CAMERA_INDEX` | `0` | OpenCV index of the laptop webcam |
| `CAMERA_MAX_FRAME_AGE` | `1.0` | Seconds before a frame is treated as stale |
| `XIAO_RETURN_DELAY` | `2.0` | Seconds the XIAO must be stable before `auto` switches back to it |

`.env` is gitignored and **overrides** variables already set in the shell.

**Camera modes.** `auto` prefers the XIAO, falls back to the laptop webcam when the XIAO stream drops,
and returns to the XIAO after it has been stable for `XIAO_RETURN_DELAY`. Any camera switch or reconnect
resets the region tracker, so a lock never carries across cameras.

> **Temporary:** the laptop-webcam fallback exists only so team members without the XIAO can develop
> and test vision. It will be removed (or pinned to `xiao`) before pilot and evaluation trials.

### Run

```bash
cd src/cavia/vision
python objdet.py
```

Window keys: `L` laptop camera · `X` XIAO · `A` auto · `Q` / `Esc` quit (mode changes are runtime-only).

### Current capabilities

- XIAO ESP32-S3 MJPEG receiver that keeps only the newest frame; laptop-webcam fallback
- YOLO detection on the controlled COCO classes
- Fixed centre reticle for object and region targeting
- Class-specific functional-region rules
- Temporal tracking: `NO_OBJECT`, `SEARCHING`, `LOCKED`, `LOST`
- Structured object-region results printed as JSON (to be published as `VisionResult` on the bus)

The XIAO camera sensor profile (VGA, JPEG quality 12, mirror/flip, AEC2) is in
`src/firmware/xiao-camera/xiao_camera_profile.h`.

Interface contracts: [`docs/interfaces.md`](../../docs/interfaces.md).
