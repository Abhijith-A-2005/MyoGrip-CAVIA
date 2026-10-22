# Architecture

Status tags: **CONFIRMED** = agreed and frozen · **ASSUMPTION** = working value, to be validated · **OPEN** = undecided.

## 1. System overview

```text
 XIAO ESP32-S3 Sense ──Wi-Fi MJPEG──►  LAPTOP (CAVIA runtime, Python)
   (OV2640, 640x480)                    ┌───────────────────────────────────────────────┐
                                        │ vision ─► arbitration ─► menu ─┐               │
                                        │                                ├─► event bus ─┼─► dashboard (FastAPI + WS ─► browser)
                                        │ fsm mirror ◄── bridge ◄────────┘               │
                                        │                                └─► logger (JSONL) ─► eval/analysis
                                        └───────────────▲───────────────┬───────────────┘
                                                        │ BLE           │ BLE
                                         status/events  │               │ menu
                                        ┌───────────────┴───────────────▼───────────────┐
                                        │ NPG LITE (ESP32-C6, firmware)                  │
                                        │ ADC 3ch ─► EMG processor ─► gesture detector   │
                                        │        ─► interaction FSM ─► grip controller   │
                                        │        ─► PCA9685 (I²C) ─► 5 × MG996R servos   │
                                        └────────────────────────────────────────────────┘
```

**CONFIRMED**
- Laptop does all vision, CAVIA, UI, logging and evaluation.
- NPG Lite holds **FSM authority**: gesture detection, menu navigation, actuation and safety limits run on-device,
  so actuation never depends on BLE latency. The laptop sends the menu and mirrors the FSM state.
- Physical servo-power E-stop sits outside all software.

**Development path (CONFIRMED):** every embedded component is first prototyped in Python on the laptop
(`keyboard_sim.fsm`, `keyboard_sim.emg`), verified against the same test vectors, then ported to C.
A **keyboard EMG emulator** and **CSV replay** stand in for real EMG until the device path works,
so CAVIA, the dashboard and the evaluation pipeline never wait on hardware.

## 2. Laptop runtime: target package layout

```text
src/cavia/
├── core/          contracts.py (message dataclasses), grips.py (grip library), config.py, bus.py (pub/sub)
├── vision/        camera source (XIAO / laptop fallback), detector, regions, tracker → publishes VisionResult
├── arbitration/   candidates.py, preferences.py, confidence.py, menu_policy.py, profiles.py
├── fsm/           Python reference FSM (mirror of myogrip_fsm.c) + test vectors
├── emg/           offline gesture detector (from CSV), keyboard emulator, replay source
├── bridge/        BLE link to NPG Lite (menu out, events/status in)
├── runtime/       orchestrator: wires sources, CAVIA, FSM, logger, dashboard; evaluation condition switch
├── dashboard/     FastAPI app, WebSocket state stream, annotated-frame MJPEG, static web UI
└── eval/          trial logger, metrics, questionnaires, analysis scripts/notebooks
```

One process, one in-process event bus. Vision runs in its own thread (YOLO is blocking);
everything else is asyncio. Every bus message is also appended to the session JSONL log.

## 3. Vision pipeline (Diya & Meghna)

```text
CameraSource (XIAO MJPEG, or laptop webcam in dev) → newest frame only, stale > 1 s dropped
  → YOLO detect → filter to controlled classes
  → reticle hit-test → class-specific region rule → candidate {object, region, det_conf, reticle_score}
  → RegionTracker (window 8, min 5 frames, hysteresis) → NO_OBJECT | SEARCHING | LOCKED | LOST
  → VisionResult (region_confidence = 0.4·det + 0.2·reticle + 0.4·stability)   [ASSUMPTION weights]
```

**Camera source (`vision/camera_source.py`).** Modes `auto` / `xiao` / `laptop`, set in `vision/.env`
and switchable at runtime (L / X / A). `auto` prefers the XIAO, falls back to the laptop webcam,
and returns to the XIAO after `XIAO_RETURN_DELAY` of stable frames. Every camera switch or reconnect
starts a new session and resets the tracker. **TEMPORARY (D14):** the fallback exists so teammates
without the XIAO can develop; trials use the XIAO only.

**XIAO sensor profile (`src/firmware/xiao-camera/xiao_camera_profile.h`):** VGA 640×480, JPEG quality 12,
horizontal mirror + vertical flip (mount orientation), AEC2 on.

**Controlled object set: OPEN.** Spec: mug, bottle, pen, spoon, phone, remote, small box.
COCO (current YOLO) has no pen or box; code uses `toothbrush` and `book` as proxies.
Options: keep COCO proxies (zero training cost) or fine-tune on a small custom set.

**Known limitations to document:** regions come from the axis-aligned box, not a mask or the object's
orientation; cup-handle side is inferred only from horizontal offset. Upgrade path: `yolo*-seg` masks.

## 4. CAVIA algorithm (Abhijith & Adwaith)

Triggered once when vision reaches `LOCKED`. Produces a **frozen menu snapshot**: small camera motion
must not reorder an open menu. Fresh interpretation only via HE → CAVIA Home.

### 4.1 Candidate generation: mechanical compatibility (ASSUMPTION, calibrate on real hand)

| Object / region | Compatible grips (default order) |
|---|---|
| cup / body | power, lateral |
| cup / handle | lateral, pinch |
| bottle / body | power |
| bottle / cap | tripod, pinch |
| toothbrush(pen) / handle | tripod, lateral, pinch |
| toothbrush(pen) / shank | pinch, tripod |
| spoon / handle | lateral, tripod |
| cell phone, remote / side_edge | lateral, pinch |
| cell phone, remote / lower_support | power, lateral |
| book(box) / side_edge | lateral, pinch |
| book(box) / cover_face | power |

Only grips flagged `calibrated` in the grip library may appear. Mechanical capability overrides preference.

### 4.2 Preference scoring

Table keyed by `(user, object, region, grip) → count`. Smoothed share over compatible grips `G`:

```text
p(g) = (count(g) + α) / (N + α·|G|)        α = 1, N = Σ count over G
```

Update rules:
- +1 only when a confirmed grip **reaches actuation** (grip_progress > 0.2, ASSUMPTION) and is not cancelled within 2 s.
- Immediate cancel (HE before closing) → no update. Full-Menu override of a grip outside `G` → logged, not counted in `G`.
- Ties broken by the default order in 4.1 (stable cold-start ranking).

### 4.3 Confidence and menu policy (thresholds ASSUMPTION, all in config)

```text
V = vision region_confidence          N = evidence count for (user, object, region)
p1, p2 = top two smoothed shares      m = p1 − p2
```

| Condition | Policy | Menu shown |
|---|---|---|
| `V < 0.6` or `N < 3` (cold start) | `FULL_COMPATIBLE` | all of `G`, ranked |
| otherwise, unless next row holds | `TOP_TWO` | top 2 of `G` |
| `V ≥ 0.8` and `N ≥ 5` and `p1 ≥ 0.7` and `m ≥ 0.3` | `ONE_CONFIRM` | top 1 (still requires LF) |

`|G| = 1` → `ONE_CONFIRM` regardless. LE always opens the Full Menu (all calibrated grips).

### 4.4 Evaluation conditions (CONFIRMED: 3 conditions)

Implemented as a runtime switch so the same code runs every trial:

| ID | Condition | Vision | Ranking | Menu sizing |
|---|---|---|---|---|
| C1 | Manual cycling | off | fixed grip order | always Full Menu |
| C2 | Static CAVIA | on | default order (4.1) | always `FULL_COMPATIBLE` |
| C3 | Adaptive CAVIA | on | preference (4.2) | confidence policy (4.3) |

C2 vs C1 isolates the value of vision; C3 vs C2 isolates preference + adaptation.

### 4.5 User profiles

One JSON file per user under `data/profiles/<user_id>.json` holding the preference table and
per-user EMG thresholds. Reset supported. Profiles of study participants use anonymous IDs (P01…).

## 5. EMG and FSM (firmware)

Frozen FSM: `assets/figures/emg-fsm.png`. Gesture vocabulary SF/SE/LF/LE/HE/REST/INVALID.

```text
raw ADC (250 Hz) → band/notch + rectify → 100 ms RMS envelope → per-user thresholds
  → FLEX_PENDING / EXT_PENDING classification (duration, amplitude, channel dominance)
  → single event → LOCK → stable REST → ready
```

Gaps in current `myogrip_fsm.c` (to close before hardware integration):
1. No `grip_progress`. LF must not set `wait_release`, and fully open must stay in actuation (D16).
   Negative `dt` must not move the hand; abort (`HOME`) mid-grip must open first (D17).
2. HE in actuation must run controlled opening to 0.0, then enter Full Menu.
3. Menu sizes are compile-time constants (3/5); must accept the menu sent by CAVIA.
4. No gesture detector on-device yet; no PCA9685 driver.
5. Selftest task is enabled by default.

**ASSUMPTION:** 250 Hz sampling is enough for envelope-based events (Test 1 shows separation);
500 Hz is a FUTURE OPTION if SF/LF or SE/LE/HE overlap is too high.

**OPEN:** Channel 3 role. Currently favoured for motion-artifact / intent validation, not a new command.

## 6. Dashboard (Adwaith & Meghna)

FastAPI serves the built web UI (`src/dashboard/web/dist/`), an MJPEG endpoint of the raw camera
frame, and a WebSocket that pushes bus state to the browser (protocol: `docs/interfaces.md` §9).
The browser draws the overlays itself (reticle, object box, region highlight), so they match the theme.

Panels: wrist camera, target (object, region, confidence ring, evidence bars), hand (state rail, grip
progress column, active grip), Adaptive and Full menus side by side with "moves to reach" on every item,
EMG timeline (gestures and activity duration bars), system status. Experimenter drawer: participant,
condition, start/end trial, grasp outcome, notes. A second page holds the evaluation results.

Two dashboards are being built in parallel from `DASHBOARD_BRIEF.md` (Adwaith on `feat/cavia-dashboard`,
Meghna separately); the team keeps the better one (D20).

## 7. Evaluation (Adwaith & Meghna)

Metrics are computed **only from JSONL logs** (see `docs/interfaces.md` §6):

| Metric | Definition |
|---|---|
| EMG command count | discrete events (SF/SE/LF/LE/HE) from menu shown to confirming LF |
| Grip selection time | menu shown → confirming LF |
| Incorrect selection | confirmed grip ≠ instructed target grip |
| First-option acceptance | confirmed grip = menu item 0 with zero navigation events |
| Grasp success | experimenter-marked outcome per trial |
| False EMG activations | events emitted during instructed-rest windows |

Questionnaires (per condition): NASA-TLX raw (workload), SUS (ease of use), and short Likert items
for perceived control and confidence. Analysis: mean ± SD, boxplots per condition, per-user comparison,
adaptation-over-time (metric vs trial index in C3).
