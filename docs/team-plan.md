# Team Plan

Working end date: **2026-11-22** (5 weeks from 2026-10-19). Status: ☐ todo · ◐ in progress · ☑ done.

## Ownership

| Stream | Owners | Scope |
|---|---|---|
| FSM, laptop side | Adwaith | Python reference FSM, simulator, CAVIA ↔ FSM integration |
| FSM, device side | Abhijith | `myogrip_fsm.c`, gesture detector, BLE protocol |
| Vision pipeline | Diya, Meghna | preprocessing, detection, reticle, functional regions, targeting, vision confidence, failure handling |
| CAVIA algorithm | Abhijith, Adwaith | candidates, preference scoring, confidence, ranking, adaptive-menu policy, profiles, FSM integration |
| Dashboard + Evaluation | Adwaith, Meghna | live dashboard, logging, metrics, questionnaires, analysis |
| Hand, servos, power | **OPEN (Q1)** | PCA9685, grip trajectories, mechanics, power and E-stop |

## Milestones

| Week | Dates | Milestone (exit criterion) |
|---|---|---|
| W1 | Oct 19–25 | **Foundation:** contracts, Python FSM passes the C selftest vectors, vision publishes `VisionResult`, keyboard EMG works |
| W2 | Oct 26–Nov 1 | **Simulated end-to-end loop:** camera → CAVIA menu → keyboard EMG → FSM → dashboard → JSONL → metrics script |
| W3 | Nov 2–8 | **Device path:** offline detector validated on CSVs, BLE bridge, firmware takes dynamic menus, one servo via PCA9685 |
| W4 | Nov 9–15 | **Integration + pilot:** hand moves from confirmed grips; pilot trial run with 1–2 users; thresholds tuned |
| W5 | Nov 16–22 | **Study + results:** C1/C2/C3 trials, questionnaires, analysis, figures, report, demo |

**Fallback (W3–W4):** if on-device detection slips, run the detector on the laptop for menu events only
(no actuation risk) and keep actuation on the NPG. CAVIA metrics (command count, selection time,
first-option acceptance, incorrect selection) do not need the hand, so the study can proceed on screen.

## Week 1 tasks (Oct 19–25)

| Task | Owner | Status |
|---|---|---|
| Repo foundation: CLAUDE.md, docs, package layout, cleanup | Adwaith | ☑ |
| `core/contracts.py`, `core/grips.py`, `core/bus.py`, config | Adwaith | ☑ |
| Python reference FSM + shared vectors (`tests/fsm/vectors.json`, ported from the 33 C selftest cases) | Adwaith | ☑ |
| Keyboard EMG emulator + `python -m keyboard_sim.fsm.sim` | Adwaith | ☑ |
| WASDE key mapping with hold-to-actuate, simulator window (D15) | Adwaith | ☑ |
| Update `myogrip_fsm.c` to pass the shared vectors (dynamic menu, `grip_progress` + tick, HE controlled opening, no gate after LF, fully open stays in actuation (D16), abort opens before HOME and clamps negative dt (D17), selftest off by default) | Abhijith | ☐ |
| Offline EMG gesture detector prototype on recorded CSVs (Python) | Abhijith | ☐ |
| Finalize BLE `MENU` / `EV` / `ST` protocol (`docs/interfaces.md` §7) | Abhijith | ☐ |
| XIAO streaming integration + camera source with laptop-webcam fallback (`camera_source.py`, `.env`) | Abhijith | ☑ |
| XIAO camera sensor profile (`src/firmware/xiao-camera/xiao_camera_profile.h`) | Abhijith | ☑ |
| Commit full XIAO camera sketch + board settings README (Wi-Fi credentials in a gitignored secrets file) | Abhijith | ☐ |
| Refactor `objdet.py` into an importable `VisionPipeline` publishing `VisionResult` (pull first: builds on `camera_source.py`) | Diya | ☐ |
| Decide object set (Q2); collect test images/clips per object & region | Meghna | ☐ |
| Candidate table + preference store + menu policy v1 with unit tests | Adwaith | ☐ |
| Dashboard UI from `DASHBOARD_BRIEF.md` (version A on `feat/cavia-dashboard`, mock mode) | Adwaith | ☑ |
| Dashboard UI from `DASHBOARD_BRIEF.md` (version B) | Meghna | ◐ |
| Resolve Q1 (hardware ownership) | Team | ☐ |

## Week 2 tasks (Oct 26–Nov 1)

| Task | Owner | Status |
|---|---|---|
| Runtime orchestrator + condition switch (C1/C2/C3) | Abhijith, Adwaith | ☐ |
| Profiles (JSON) + preference updates from FSM outcomes | Adwaith | ☐ |
| Vision: region confidence tuning, failure states shown on overlay, FPS/latency measurement | Diya, Meghna | ☐ |
| Compare dashboards A and B, keep one (D20) | Team | ☐ |
| FastAPI backend serving the dashboard protocol (`docs/interfaces.md` §9): skeleton, hub, session (`cavia.server`) | Adwaith | ☑ |
| Integration: vision results to the dashboard (live, record, replay) | Adwaith | ☑ |
| Integration: camera MJPEG, menus/FSM/EMG to the dashboard | Adwaith | ◐ |
| JSONL logger + metrics script on simulated sessions | Adwaith | ☐ |
| Questionnaire forms (NASA-TLX, SUS, control/confidence Likert) | Meghna | ☐ |
| Remove camera `auto` / laptop fallback or pin `CAMERA_MODE=xiao` before pilot (D14) | Abhijith, Diya | ☐ |

## Week 3–5 tasks

Planned in detail at the end of W2 once Q1 is resolved and the simulated loop works.
