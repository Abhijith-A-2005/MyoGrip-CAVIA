# Decision Log

Newest first. A later entry overrides anything earlier, in this file or any other doc.

| # | Date | Decision | Why |
|---|---|---|---|
| D13 | 2026-10-19 | FSM behaviour is defined by `tests/fsm/vectors.json`; Python and C FSMs must both pass it. Full Menu = 4 calibrated grips (C test used 5) | One spec, two implementations, no drift |
| D12 | 2026-10-19 | Evaluation reduced to 3 conditions: C1 Manual cycling, C2 Static CAVIA, C3 Adaptive CAVIA | ~5 weeks left; these three still isolate vision benefit (C2 vs C1) and preference + adaptation benefit (C3 vs C2) |
| D11 | 2026-10-19 | Dashboard = FastAPI + WebSocket backend, browser UI | Decoupled from vision loop, demo-friendly, parallel frontend work |
| D10 | 2026-10-19 | FSM authority and gesture detection live on NPG firmware; laptop mirrors state. Prototype in Python first | Actuation must not depend on BLE latency/dropouts |
| D9 | 2026-10-19 | Integration-first: keyboard EMG emulator + CSV replay so CAVIA, dashboard and evaluation run before hardware is ready | Late integration is the top project risk |
| D8 | 2026-10-19 | All evaluation metrics are computed from JSONL session logs | Reproducible analysis; no hand-tallied numbers |
| D7 | — | Fully open after actuation returns to Full Menu; Full Menu + HE → CAVIA Home | Re-grip same object without re-analysis |
| D6 | — | Actuation = Closing / Holding / Opening with constant-speed, duration-controlled `grip_progress` | Predictable, safe; no amplitude-proportional speed |
| D5 | — | HE is Back/Cancel, not E-stop; physical servo-power cutoff is the E-stop | Software gesture is not a safety guarantee |
| D4 | — | Full Menu contains all calibrated grips, not just region-compatible ones | Explicit override, preserves agency, measures CAVIA disagreement |
| D3 | — | Gesture map: SF Next, SE Previous, LF Confirm, LE Full Menu, HE Back | Frozen FSM (`assets/figures/emg-fsm.png`) |
| D2 | — | No FSR, EEG/ErrP, EOG or ECG in the MVP | Scope and feasibility |
| D1 | — | Camera = XIAO ESP32-S3 Sense (OV2640); servo driver = PCA9685; 5 × MG996R-class servos | Hardware checkpoint |

## Open questions

| # | Question | Owner | Needed by |
|---|---|---|---|
| Q1 | Who owns hand mechanics, PCA9685/servos, power? (EMG detector → Abhijith) | Team | Week 1 |
| Q2 | Controlled object set: COCO proxies (toothbrush = pen, book = box) or fine-tune? | Diya & Meghna | Week 2 |
| Q3 | Channel 3 role (artifact rejection / intent validation)? | EMG owner | Week 3 |
| Q4 | Final menu-policy thresholds (V, N, p1, margin) | Abhijith & Adwaith | Pilot, Week 4 |
| Q5 | Participants: how many, who, ethics/consent form | Team + guide | Week 3 |
| Q6 | Confirm: extensor activity while already fully open (right after LF) → straight to Full Menu (vector `he_while_already_open…`, C case 26→27) | Abhijith, Adwaith | Week 1 |
