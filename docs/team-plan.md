# Team Plan

Working end date: **2026-11-22** (5 weeks from 2026-10-19). Status: ☐ todo · ◐ in progress · ☑ done.

## Ownership

| Stream | Owners | Scope |
|---|---|---|
| Vision pipeline | Diya, Meghna | preprocessing, detection, reticle, functional regions, targeting, vision confidence, failure handling |
| CAVIA algorithm | Abhijith, Adwaith | candidates, preference scoring, confidence, ranking, adaptive-menu policy, profiles, FSM integration |
| Dashboard + Evaluation | Adwaith, Meghna | live dashboard, logging, metrics, questionnaires, analysis |
| EMG detector, firmware, hand, servos, power | **OPEN (Q1)** | gesture detector, PCA9685, grip trajectories, mechanics, power and E-stop |

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
| Repo foundation: CLAUDE.md, docs, package layout, cleanup | Adwaith | ◐ |
| `core/contracts.py`, `core/grips.py`, `core/bus.py`, config | Adwaith | ☐ |
| Python reference FSM + port of the 33 C selftest vectors as pytest | Abhijith | ☐ |
| Keyboard EMG emulator (SF/SE/LF/LE/HE + hold keys for flex/ext activity) | Abhijith | ☐ |
| Refactor `objdet.py` into an importable `VisionPipeline` publishing `VisionResult` | Diya | ☐ |
| Decide object set (Q2); collect test images/clips per object & region | Meghna | ☐ |
| Candidate table + preference store + menu policy v1 with unit tests | Adwaith | ☐ |
| Dashboard skeleton: FastAPI, WebSocket, MJPEG, static page | Meghna | ☐ |
| Resolve Q1 (hardware ownership) | Team | ☐ |

## Week 2 tasks (Oct 26–Nov 1)

| Task | Owner | Status |
|---|---|---|
| Runtime orchestrator + condition switch (C1/C2/C3) | Abhijith, Adwaith | ☐ |
| Profiles (JSON) + preference updates from FSM outcomes | Adwaith | ☐ |
| Vision: region confidence tuning, failure states shown on overlay, FPS/latency measurement | Diya, Meghna | ☐ |
| Dashboard: all panels + experimenter controls (user, condition, trial start/end, outcome) | Meghna, Adwaith | ☐ |
| JSONL logger + metrics script on simulated sessions | Adwaith | ☐ |
| Questionnaire forms (NASA-TLX, SUS, control/confidence Likert) | Meghna | ☐ |
| Offline EMG detector from `data/emg/` CSVs (Python) | Q1 owner | ☐ |

## Week 3–5 tasks

Planned in detail at the end of W2 once Q1 is resolved and the simulated loop works.
