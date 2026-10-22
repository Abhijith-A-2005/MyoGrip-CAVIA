# Interface Contracts

Every message crossing a module boundary uses these shapes. Python implementations live in
`src/cavia/core/contracts.py`. Change this doc and the code in the same commit.

All timestamps are `ts`: float seconds from `time.monotonic()` on the laptop, plus `wall`: Unix time,
on logged records only.

## 1. Enumerations

```text
Grip         OPEN=0  POWER=1  PINCH=2  TRIPOD=3  LATERAL=4        (ids are wire values; never renumber)
VisionState  NO_OBJECT | SEARCHING | LOCKED | LOST
EmgEvent     SF | SE | LF | LE | HE | REST | INVALID               (discrete, menu mode)
Activity     REST | FLEX_ACTIVE | EXT_ACTIVE | INVALID              (continuous, actuation mode)
FsmState     HOME | ADAPTIVE | FULL | CLOSING | HOLDING | OPENING
MenuPolicy   FULL_COMPATIBLE | TOP_TWO | ONE_CONFIRM | FULL_MENU
Condition    C1_MANUAL | C2_STATIC | C3_ADAPTIVE
```

## 2. VisionResult (vision → bus)

Published once per processed frame.

```json
{
  "ts": 1234.567, "frame_seq": 812,
  "state": "LOCKED",
  "object": "cup", "region": "handle",
  "region_confidence": 0.87,
  "det_conf": 0.91, "reticle_score": 0.64, "stability": 0.88,
  "stable": true
}
```

`object`/`region` are `null` when `state == NO_OBJECT`.

## 3. MenuProposal (CAVIA → bus → bridge → NPG)

In live keyboard simulation, a fresh stable LOCKED result creates a menu.
Before LF confirmation, valid new object/region locks and confidence policy-band
changes can update it.

Tracking loss retains the last menu, context and selection. An unknown region
of the same object retains its previous known-region menu.

LF confirmation freezes the displayed context and pauses detection until HOME,
including time spent in Full Menu after HE. HOME clears the menu and starts
a fresh detection cycle.

The reference FSM still loads menus only at HOME. The live simulator adapter
reloads only unconfirmed, zero-progress menus. Firmware integration is separate.

MenuProposal construction rejects an empty full_menu, mismatched scores/items,
OPEN in the selectable grips, or duplicated grips. items may be empty for the
FULL_MENU policy.

```json
{
  "ts": 1235.010, "menu_id": 17,
  "condition": "C3_ADAPTIVE",
  "context": {"object": "cup", "region": "handle", "region_confidence": 0.87},
  "policy": "TOP_TWO",
  "items": ["LATERAL", "PINCH"],
  "scores": [0.71, 0.29],
  "confidence": {"vision": 0.87, "evidence_n": 6, "top_share": 0.71, "margin": 0.42},
  "full_menu": ["POWER", "PINCH", "TRIPOD", "LATERAL"]
}
```

`full_menu` = all calibrated grips except OPEN, in fixed order.

## 4. EMG input (source → FSM)

```json
{"ts": 1236.2, "source": "keyboard", "event": "SF"}
{"ts": 1240.9, "source": "device",   "activity": "FLEX_ACTIVE"}
```

`source ∈ {device, keyboard, replay}`. Exactly one of `event` / `activity`.

## 5. FsmStatus (NPG or Python FSM → bus)

Published on every state change and at ≥10 Hz during actuation.

```json
{
  "ts": 1241.0, "menu_id": 17,
  "state": "CLOSING",
  "menu_kind": "ADAPTIVE",
  "selected_index": 0, "selected_grip": "LATERAL",
  "active_grip": "LATERAL", "grip_progress": 0.43,
  "wait_release": false,
  "last_event": "LF"
}
```

## 6. Log record (everything → JSONL)

One file per session: `data/sessions/<session_id>.jsonl`. One record per line:

```json
{"wall": 1760864400.12, "ts": 1235.010, "session": "S2026-10-20-P01", "user": "P01",
 "condition": "C3_ADAPTIVE", "trial": 12, "type": "menu", "data": { ...MenuProposal... }}
```

`type ∈ {session_start, trial_start, vision, menu, emg, fsm, preference_update, trial_end, note}`.
`trial_start.data` holds `{"object", "region", "target_grip"}` (the instructed task);
`trial_end.data` holds `{"grasp_success": bool, "notes": str}` (experimenter-marked).

Vision records may be decimated to state changes only to keep logs small.

## 7. Laptop ↔ NPG BLE protocol (DRAFT, firmware owner to finalize)

Existing service `4fafc201-1fb5-459e-8fcc-c5c9c331914b`:
- Data characteristic (notify): raw 3-channel EMG, 25 samples × 7 bytes. Unchanged.
- Control characteristic (read/write/notify): ASCII commands, **< 20 bytes**.

Proposed additions on the control characteristic:

| Direction | Command | Meaning |
|---|---|---|
| laptop → NPG | `MENU <id> <g0>[,<g1>...]` | load adaptive menu, grip ids from §1, e.g. `MENU 17 4,2` |
| laptop → NPG | `FULL <g0>,<g1>,...` | set full-menu contents (sent once at session start) |
| laptop → NPG | `HOME` | experimenter abort: if a grip is active, controlled opening to 0.0 first, then HOME (D17) |
| NPG → laptop | `EV <event>` | discrete event detected, e.g. `EV SF` |
| NPG → laptop | `ST <state> <sel> <grip> <prog%>` | FSM status, e.g. `ST CLOSING 0 4 43` |

`ST` notifications on state change and every 100 ms during actuation.

## 8. Live keyboard integration transport

`python -m cavia --user 1` starts vision in a child process and the arbitration
keyboard simulator in the parent. SQLite and FSM operations remain on the
simulator thread.

### Vision results

The launcher supplies CAVIA_RESULT_PORT. Vision sends tracker output through
a nonblocking localhost UDP socket, adding:

- ts: monotonic emission timestamp.
- generation: non-negative integer identifying the detection generation.

Existing fields remain state, object, region, region_confidence and stable.
region_confidence maps to ArbitrationInput.vision_confidence.

For the dashboard (§9) each result also carries: `det_conf`, `reticle_score`, `stability` (the parts
of region_confidence), `source` (`XIAO`/`LAPTOP`), `frame_seq`, and `box` / `region_box`
(`[x1, y1, x2, y2]` normalised 0..1, or null). The boxes are sent only when the frame's detection
matches the reported object/region; `region_box` comes from `regions.region_rect`, which mirrors the
class-specific zone rules. The arbitration runtime ignores these fields.
A null region maps to unknown.

The receiver rejects malformed, out-of-order, pre-HOME and wrong-generation
results. No vision result is accepted while paused.

Before the first lock, no actionable menu is shown. After a lock, LOST,
SEARCHING, NO_OBJECT, timeout and process exit retain the last menu and selection.
The status identifies it as LAST LOCK; deliberate confirmation remains available.

An unknown region on the same object does not erase a known region. A valid
new region or different object lock may replace it before confirmation.
Confidence policy-band changes may also update an unconfirmed menu.

The current interface identifies object classes, not physical object instances.
Distinguishing two cups by identity requires a future vision tracking ID.

### Camera frames (dashboard only)

When launched by the dashboard server, vision also gets `CAVIA_FRAME_PORT` and sends the raw camera
frame (no drawings) over a localhost TCP connection: `[uint32 length][float64 capture time,
time.monotonic][JPEG]`, at most about 20 fps and at most 2 MB per frame. A single-slot sender keeps
only the newest frame, so a slow server can never delay detection. Frames keep flowing while detection
is paused. Without `CAVIA_FRAME_PORT` nothing is encoded or sent. The server serves them at `/video`.

### Detection control

The launcher sets CAVIA_CONTROL_STDIN=1 and opens the child's stdin as a pipe.
Each command is one JSON line containing paused and generation.

Examples:
{"paused": true, "generation": 1}
{"paused": false, "generation": 2}

A background reader updates the detector's control snapshot.
Actual LF confirmation sends PAUSE immediately.

While paused, vision skips YOLO, contour/region processing and tracker updates.
Camera capture, preview and the loaded model remain available.
An inference already running may finish, but its obsolete output is rejected.

HE from actuation opens to Full Menu. Detection remains paused there.
Reconfirming a grip or fully opening the hand does not resume detection.

HOME clears the menu, sends RESUME and advances the generation.
Vision resets tracking, and the simulator requires fresh matching-generation
results with released keys before loading the next menu.

Without the launcher control environment, standalone vision runs continuously.

### History

Retaining or redisplaying a menu creates no new selection record.
Confirmation refers to the displayed menu snapshot.

Existing simulator preference-acceptance rules remain unchanged:
2 seconds and maximum simulated progress >= 0.2.
grasp_success remains unknown.

## 9. Dashboard protocol (backend ↔ browser)

Server: `src/cavia/server/` (`python -m cavia.server`). Client: `src/dashboard/`. TypeScript mirror:
`src/dashboard/web/src/types/messages.ts`.

Endpoints: `ws://<host>:8000/ws` (state), `http://<host>:8000/video` (MJPEG of the raw camera frame;
the dashboard draws its own overlays; 503 until the first frame, and the stream ends after 5 s without
a new frame), and the built UI from `src/dashboard/web/dist/`. `system.camera.fps` and `latency_ms`
(capture to server) come from the frame stream when it is flowing; `latency_ms` 0 means not measured.

Every server message is `{"type": "<kind>", "data": {...}}`. On connect the server sends one `snapshot`,
then incremental messages.

| `type` | `data` | When |
|---|---|---|
| `snapshot` | `{vision, menu, fsm, system, session, emg_recent: []}` | once per connection |
| `vision` | `VisionResult` (§2) **plus** `source` (`XIAO`/`LAPTOP`), `box`, `region_box` | every processed frame |
| `menu` | `MenuProposal` (§3), or `null` to clear both menus | on lock, and on return to HOME |
| `fsm` | `FsmStatus` (§5) **plus** `returning: bool` (HE controlled opening in progress) | every change, ≥10 Hz in actuation |
| `emg` | `EmgInput` (§4) | each discrete event and each activity change |
| `system` | `{camera: {status, source, fps, latency_ms}, vision: {status, model}, hand_link: {status, battery_pct}, emg_source}` | about 1 Hz |
| `session` | `{participant, condition, trial, trial_active}` | on change |

`box` and `region_box` are `[x1, y1, x2, y2]` normalised 0..1 in frame coordinates, or `null`.
`status` values: `live` / `ok` / `connected`, `degraded`, `stale` / `down` / `disconnected`.

**Ordering rule:** send the `emg` message for a gesture **before** the `fsm` update it causes. The
dashboard tags each gesture with the FSM state it arrived in (menu or actuation).

Browser → server:

```json
{"type": "key", "data": {"key": "a", "down": true}}
{"type": "control", "data": {"action": "start_trial"}}
{"type": "control", "data": {"action": "end_trial", "grasp_success": true, "notes": ""}}
{"type": "control", "data": {"action": "set_session", "participant": "P02", "condition": "C2_STATIC"}}
```

`key` messages carry real key-down/up for `w a s d e` only (keyboard EMG mode); the backend applies the
same rules as `keyboard_sim.emg.keyboard.KeyboardEmg`. Control actions become `trial_start` / `trial_end` /
`session_start` records in the session log (§6).

The server drives `LiveSimApp` (§8) on one runtime thread: `menu` is the controller's current
`decision.proposal`, `fsm` is its FSM status, and `emg` events are the gestures that reached the FSM from a
real key press (the controller's own internal calls are not reported). `set_session` is accepted only at
CAVIA Home with all keys released and only for `C3_ADAPTIVE`; the participant ID selects the preference
profile. Rejected controls are logged as `control_rejected`.
