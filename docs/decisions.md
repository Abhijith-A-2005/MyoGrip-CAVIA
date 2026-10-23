# Decision Log

Newest first. A later entry overrides anything earlier, in this file or any other doc.

| # | Date | Decision | Why |
|---|---|---|---|
| D22 | 2026-10-23 | Users are preference profiles listed from a `users` table plus the selection history; the dashboard adds users and switches them from the header. Switching is allowed until a grip is confirmed (it clears an unconfirmed menu), not only at HOME. A History page reads `GET /api/history` through a separate read-only SQLite connection. The Target panel drops the detection / on-target / stability bars and becomes a narrow column (ring above the names), so the camera viewfinder grows to 16:9 (the 4:3 frame fills its width; thin top and bottom strips are cut off) | With the camera on an object the menu re-locks almost at once, so a HOME-only rule made switching impractical; clearing an unconfirmed menu loses nothing. Read-only history keeps the runtime thread the only writer. The bars were diagnostic detail; the values stay in the logs |
| D21 | 2026-10-22 | `python -m cavia.server` runs the same LiveSimApp as `python -m cavia --user 1`, with keys from the dashboard. The controller, its SQLite store and vision polling share one runtime thread. The drawer's participant ID is the preference profile. Live mode serves Adaptive CAVIA (C3) only until the engine implements C1/C2 | LiveSimApp, VisionProcess and SQLite connections are single-threaded; one controller keeps dashboard and pygame behaviour identical; showing another condition while serving C3 menus would corrupt the study |
| D20 | 2026-10-22 | Dashboard (`feat/cavia-dashboard`): React + Vite on a fixed 1920×1080 stage scaled to the window; hash routes; focus is a pure function of FSM state; mock mode runs a TypeScript port of the FSM checked against `tests/fsm/vectors.json`. Two dashboards are built in parallel from the brief and the better one is kept | Same layout on projector and laptops; no backend routing rules; mock behaves exactly like the real FSM |
| D19 | 2026-10-21 | Retain the last locked menu and selection through focus loss, unresolved region, source timeout and disconnect. LF freezes context and pauses detection through actuation and Full Menu. HOME clears the menu, advances the detection generation, resets tracking and resumes. Supersedes D18's output-only vision hook | Prevents disappearing menus and unused inference. Generation checks prevent old work from restoring a pre-HOME lock. Camera capture and preview remain running |
| D18 | 2026-10-21 | Live keyboard integration updates menus from stable vision until LF confirmation, then freezes context through actuation and Full Menu until HOME. Add a runtime adapter and output-only vision hook | Keeps confirmation and history tied to the displayed snapshot. Firmware integration remains separate |
| D17 | 2026-10-19 | Experimenter abort (BLE `HOME`) during a grip runs the controlled opening first, then HOME; FSM speeds must be > 0; negative tick time is ignored | A plain reset would leave the hand closed in HOME, where extension is ignored, and the next grip would start half-closed |
| D16 | 2026-10-19 | (a) LF confirm no longer sets the release gate: continued flexion after LF closes immediately. (b) Reaching fully open stays in actuation; the user may close again. Only HE leaves a grip (controlled opening → Full Menu). Supersedes D7's "fully open → Full Menu" | Faster, more natural grasping; re-grasp with the same grip without re-selecting. INVALID still requires rest |
| D15 | 2026-10-19 | Keyboard EMG emulator uses W SE (up), S SF (down), A LF (confirm), D LE (full menu), E HE (back); in actuation, holding A / D = flexor / extensor activity. Simulator is a pygame-ce window (`sim` extra) for real key-up events | Matches the vertical menu; one key per gesture family makes hold-to-close feel like sustained EMG |
| D14 | 2026-10-19 | Camera `auto` mode with laptop-webcam fallback is a temporary development aid; removed or pinned to `xiao` before pilot/evaluation trials | Only one XIAO exists; teammates need to test vision without it |
| D13 | 2026-10-19 | FSM behaviour is defined by `tests/fsm/vectors.json`; Python and C FSMs must both pass it. Full Menu = 4 calibrated grips (C test used 5) | One spec, two implementations, no drift |
| D12 | 2026-10-19 | Evaluation reduced to 3 conditions: C1 Manual cycling, C2 Static CAVIA, C3 Adaptive CAVIA | ~5 weeks left; these three still isolate vision benefit (C2 vs C1) and preference + adaptation benefit (C3 vs C2) |
| D11 | 2026-10-19 | Dashboard = FastAPI + WebSocket backend, browser UI | Decoupled from vision loop, demo-friendly, parallel frontend work |
| D10 | 2026-10-19 | FSM authority and gesture detection live on NPG firmware; laptop mirrors state. Prototype in Python first | Actuation must not depend on BLE latency/dropouts |
| D9 | 2026-10-19 | Integration-first: keyboard EMG emulator + CSV replay so CAVIA, dashboard and evaluation run before hardware is ready | Late integration is the top project risk |
| D8 | 2026-10-19 | All evaluation metrics are computed from JSONL session logs | Reproducible analysis; no hand-tallied numbers |
| D7 | earlier | ~~Fully open after actuation returns to Full Menu~~ (superseded by D16); Full Menu + HE → CAVIA Home | Re-grip same object without re-analysis |
| D6 | earlier | Actuation = Closing / Holding / Opening with constant-speed, duration-controlled `grip_progress` | Predictable, safe; no amplitude-proportional speed |
| D5 | earlier | HE is Back/Cancel, not E-stop; physical servo-power cutoff is the E-stop | Software gesture is not a safety guarantee |
| D4 | earlier | Full Menu contains all calibrated grips, not just region-compatible ones | Explicit override, preserves agency, measures CAVIA disagreement |
| D3 | earlier | Gesture map: SF Next, SE Previous, LF Confirm, LE Full Menu, HE Back | Frozen FSM (`assets/figures/emg-fsm.png`) |
| D2 | earlier | No FSR, EEG/ErrP, EOG or ECG in the MVP | Scope and feasibility |
| D1 | earlier | Camera = XIAO ESP32-S3 Sense (OV2640); servo driver = PCA9685; 5 × MG996R-class servos | Hardware checkpoint |

## Open questions

| # | Question | Owner | Needed by |
|---|---|---|---|
| Q1 | Who owns hand mechanics, PCA9685/servos, power? (EMG detector → Abhijith) | Team | Week 1 |
| Q2 | Controlled object set: COCO proxies (toothbrush = pen, book = box) or fine-tune? | Diya & Meghna | Week 2 |
| Q3 | Channel 3 role (artifact rejection / intent validation)? | EMG owner | Week 3 |
| Q4 | Final menu-policy thresholds (V, N, p1, margin) | Abhijith & Adwaith | Pilot, Week 4 |
| Q5 | Participants: how many, who, ethics/consent form | Team + guide | Week 3 |
| ~~Q6~~ | Resolved by D16: fully open no longer leaves actuation | n/a | n/a |
