# CAVIA Laptop Runtime

Laptop-side software for MyoGrip CAVIA (Context-Aware Visual Intent Arbitration).

| Package | Status | Contents |
|---|---|---|
| `core/` | ✅ | Message contracts, grip library, config, event bus |
| `fsm/` | ✅ | Python reference FSM (mirror of the firmware FSM) + keyboard simulator |
| `emg/` | ◐ | Keyboard EMG emulator (gesture detector and CSV replay to come) |
| `vision/` | ◐ | Camera source, YOLO detection, reticle, regions, tracker (standalone script; packaging pending) |
| `arbitration/`, `runtime/`, `dashboard/`, `eval/` | ☐ | Planned — see [`docs/architecture.md`](../../docs/architecture.md) |

## Setup

From the repository root:

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"            # core + FSM + tests (light)
pip install -e ".[vision,dev]"     # add camera + YOLO stack (heavy)
```

`pyproject.toml` declares the package and its optional dependency groups.
`vision/requirements.txt` is a pinned freeze for reproducing the exact vision environment:
`pip install -r src/cavia/vision/requirements.txt`.

## FSM simulator (no hardware)

```bash
pytest
python -m cavia.fsm.sim --menu LATERAL,PINCH
```

Keys: `1` SF · `2` SE · `3` LF · `4` LE · `5` HE · `f` flex · `e` extend · `space` rest · `x` invalid ·
`m` reload menu (from HOME) · `q` quit. `f` / `e` / `space` latch until another is pressed.

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
