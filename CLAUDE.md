# CLAUDE.md — MyoGrip CAVIA

Guidance for AI coding assistants working in this repository.

## Project in one paragraph

MyoGrip CAVIA is a B.Tech assistive-engineering research prototype (not a medical device): a low-cost,
5-servo tendon-driven hand controlled by surface EMG (NPG Lite, ESP32-C6), with a wrist camera
(XIAO ESP32-S3 Sense, OV2640) streaming to a laptop. **CAVIA** (Context-Aware Visual Intent Arbitration)
detects an object, estimates the functional region under a fixed centre reticle, ranks mechanically
valid grips by per-user preference history, and sizes the menu by confidence. The user always navigates
and confirms with EMG — **the system never executes a grip automatically.**

Research question: *Can preference-ranked, confidence-adaptive functional-region grip menus reduce EMG
command burden and selection time without increasing incorrect choices or reducing perceived control?*

## Read first

| Doc | What it holds |
|---|---|
| `docs/architecture.md` | System architecture, data flow, CAVIA algorithm |
| `docs/interfaces.md` | Message contracts between vision, CAVIA, FSM, dashboard, logger, firmware |
| `docs/decisions.md` | Decision log — **latest entry wins** over any older doc |
| `docs/team-plan.md` | Ownership, weekly milestones, status |
| `MyoGrip_CAVIA_Complete_AI_Context.md` | Full design context (gitignored; local only, may be absent) |

## Non-negotiable rules

- **Never auto-execute a grip.** LF (sustained flexion) confirmation is always required, even for a one-option menu.
- **Full Menu = all physically calibrated grips**, not only the region-compatible ones.
- **HE is Back/Cancel, not an emergency stop.** The real E-stop is a physical servo-power cutoff.
- Actuation is **constant-speed, duration-controlled** (`grip_progress` 0.0–1.0): flexor → close, rest → hold, extensor → open. Never amplitude-proportional.
- Fully open after actuation → **Full Menu**. Full Menu + HE → CAVIA Home.
- Ambiguous EMG → **no action**. One contraction → at most one event (refractory + return-to-rest).
- Do not add FSR/contact sensing, EEG/ErrP, EOG or ECG to the MVP.
- Wording: say "functional grasp-region estimate / class-specific region rule", never "affordance detection".
  Never claim force control, medical-grade performance, or intent prediction.
- The FSM firmware selftest (`MYOGRIP_SELFTEST_ENABLED`) must be `0` in any build that drives servos.

## Repository map

```text
src/cavia/vision/                 Laptop vision: MJPEG receiver, YOLO detection, reticle, regions, tracker
src/cavia/                        CAVIA laptop runtime (arbitration, fsm mirror, dashboard, eval) — being built
src/firmware/npg-lite-controller/ ESP-IDF firmware for NPG Lite (BLE EMG streaming + MyoGrip FSM). GPL-3.0
data/emg/                         Recorded EMG sessions (CSV)
assets/figures/                   Approved figures (FSM diagram, EMG characterization)
docs/                             Architecture, interfaces, decisions, plan
```

## Commands

```bash
# Vision (laptop)
pip install -r src/cavia/vision/requirements.txt
CAVIA_CAMERA_IP=<xiao-ip> python src/cavia/vision/objdet.py

# Firmware (ESP-IDF, from src/firmware/npg-lite-controller)
idf.py set-target esp32c6 && idf.py build && idf.py flash monitor -p <port>

# EMG logger (from src/firmware/npg-lite-controller/test)
python record-log.py --outfile session.csv --duration 5
```

## Conventions

- Python 3.11+, type hints, dataclasses for messages. Match surrounding style; keep comments sparse.
- All cross-module messages follow `docs/interfaces.md`. Change the doc in the same commit as the code.
- Thresholds and weights live in config, never hard-coded in logic.
- Every runtime event that matters for evaluation is logged (JSONL), so metrics can be recomputed from logs.
- When a design choice is made, append it to `docs/decisions.md`.
- Tag uncertain statements as **CONFIRMED / ASSUMPTION / OPEN QUESTION / FUTURE OPTION**.
- Commit messages: short imperative one-liners (e.g. `Add CAVIA preference store`), no trailers.
