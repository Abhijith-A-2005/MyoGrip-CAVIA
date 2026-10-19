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

Built once on `LOCKED`; frozen until FSM returns to `HOME`. Rejected at construction if `full_menu` is
empty, `scores` and `items` differ in length, `OPEN` appears, or a grip is duplicated. `items` may be
empty (C1 manual cycling uses `policy: FULL_MENU`).

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

## 7. Laptop ↔ NPG BLE protocol — DRAFT (firmware owner to finalize)

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
