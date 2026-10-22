# CLAUDE.md: MyoGrip CAVIA

Guidance for AI coding assistants working in this repository.

## Project in one paragraph

MyoGrip CAVIA is a B.Tech assistive-engineering research prototype (not a medical device): a low-cost,
5-servo tendon-driven hand controlled by surface EMG (NPG Lite, ESP32-C6), with a wrist camera
(XIAO ESP32-S3 Sense, OV2640) streaming to a laptop. **CAVIA** (Context-Aware Visual Intent Arbitration)
detects an object, estimates the functional region under a fixed centre reticle, ranks mechanically
valid grips by per-user preference history, and sizes the menu by confidence. The user always navigates
and confirms with EMG. **The system never executes a grip automatically.**

Research question: *Can preference-ranked, confidence-adaptive functional-region grip menus reduce EMG
command burden and selection time without increasing incorrect choices or reducing perceived control?*

## Read first

| Doc | What it holds |
|---|---|
| `docs/architecture.md` | System architecture, data flow, CAVIA algorithm |
| `docs/interfaces.md` | Message contracts between vision, CAVIA, FSM, dashboard, logger, firmware |
| `docs/decisions.md` | Decision log. The **latest entry wins** over any older doc |
| `docs/team-plan.md` | Ownership, weekly milestones, status |
| `MyoGrip_CAVIA_Complete_AI_Context.md` | Full design context (gitignored; local only, may be absent) |

## Non-negotiable rules

- **Never auto-execute a grip.** LF (sustained flexion) confirmation is always required, even for a one-option menu.
- **Full Menu = all physically calibrated grips**, not only the region-compatible ones.
- **HE is Back/Cancel, not an emergency stop.** The real E-stop is a physical servo-power cutoff.
- Actuation is **constant-speed, duration-controlled** (`grip_progress` 0.0–1.0): flexor → close, rest → hold, extensor → open. Never amplitude-proportional.
- Confirming LF flows straight into closing (no release needed). Inside actuation the user can close and
  open repeatedly; reaching fully open just holds there. **Only HE leaves a grip** (controlled opening →
  Full Menu). Full Menu + HE → CAVIA Home. (D16)
- Ambiguous EMG → **no action**. One contraction → at most one event (refractory + return-to-rest).
- Do not add FSR/contact sensing, EEG/ErrP, EOG or ECG to the MVP.
- Wording: say "functional grasp-region estimate / class-specific region rule", never "affordance detection".
  Never claim force control, medical-grade performance, or intent prediction.
- The FSM firmware selftest (`MYOGRIP_SELFTEST_ENABLED`) must be `0` in any build that drives servos.
- Camera `auto` mode / laptop-webcam fallback is a **temporary development aid** (D14). Pilot and evaluation
  trials use the wrist-mounted XIAO only.

## Repository map

```text
src/cavia/vision/                 Laptop vision: camera source (XIAO/laptop), YOLO, reticle, regions, tracker
src/cavia/core/                   Message contracts, grip library, config, event bus
src/keyboard_sim/fsm/             Python reference FSM (mirror of firmware) + interactive simulator
src/keyboard_sim/emg/             EMG input sources (WASDE keyboard emulator; detector/replay to come)
src/dashboard/                    Dashboard UI (React + Vite, mock mode); see src/dashboard/README.md
tests/                            pytest suite; tests/fsm/vectors.json = shared FSM spec
src/firmware/npg-lite-controller/ ESP-IDF firmware for NPG Lite (BLE EMG streaming + MyoGrip FSM). GPL-3.0
src/firmware/xiao-camera/         XIAO ESP32-S3 Sense camera sensor profile (OV2640)
data/emg/                         Recorded EMG sessions (CSV)
assets/figures/                   Approved figures (FSM diagram, EMG characterization)
docs/                             Architecture, interfaces, decisions, plan
```

## Commands

```bash
# Laptop runtime (from repo root)
python -m venv .venv && source .venv/bin/activate
pip install -e ".[sim,dev]"                          # core + simulator + tests; add ",vision" for camera/YOLO
pytest                                               # contracts, FSM vectors, keyboard, simulator
python -m keyboard_sim.fsm.sim --menu LATERAL,PINCH  # FSM window + keyboard EMG, no hardware
#   W up (SE) · S down (SF) · A confirm (LF) · D full menu (LE) · E back (HE)
#   actuation: hold A = close · hold D = open · release = hold · M reload menu · Q quit

# Dashboard (from src/dashboard/web)
npm install && npm run dev                           # http://localhost:5173, mock data, WASDE keys, ` drawer
npm run build && npm run test:fsm                    # build to dist/; mock FSM vs shared vectors

# Vision (laptop): settings in src/cavia/vision/.env (copy from .env.example)
pip install -r src/cavia/vision/requirements.txt     # pinned vision environment
cd src/cavia/vision && python objdet.py              # keys: L laptop / X XIAO / A auto / Q quit

# Firmware (ESP-IDF, from src/firmware/npg-lite-controller)
idf.py set-target esp32c6 && idf.py build && idf.py flash monitor -p <port>

# EMG logger (from src/firmware/npg-lite-controller/test)
python record-log.py --outfile session.csv --duration 5
```

## Conventions

- Python 3.11+, type hints, dataclasses for messages. Match surrounding style; keep comments sparse.
- All cross-module messages follow `docs/interfaces.md`. Change the doc in the same commit as the code.
- FSM behaviour is pinned by `tests/fsm/vectors.json`, shared by the Python FSM, `myogrip_fsm.c` and the
  dashboard's mock FSM (`npm run test:fsm`).
  Change a behaviour by changing the vectors first, then both implementations.
- Thresholds and weights live in config, never hard-coded in logic. Machine-specific settings
  (camera IP, ports) go in a gitignored `.env`; commit only `.env.example`.
- New runtime dependencies go in `pyproject.toml` (the right optional group) as well as any pinned
  `requirements.txt`.
- Pull with rebase (`git config pull.rebase true`) to keep history linear.
- Every runtime event that matters for evaluation is logged (JSONL), so metrics can be recomputed from logs.
- When a design choice is made, append it to `docs/decisions.md`.
- **Never use em dashes** (the long dash, U+2014) in any text: docs, code comments, UI copy, commit messages, chat replies.
  Use a colon, comma, full stop or parentheses instead. En dashes in number ranges (1–5) are fine.
- Tag uncertain statements as **CONFIRMED / ASSUMPTION / OPEN QUESTION / FUTURE OPTION**.
- Commit messages follow [Conventional Commits](https://www.conventionalcommits.org): `<type>(<scope>): <summary>`,
  short imperative one-liner, lowercase summary, no trailing period, no body or trailers.
  - Types: `feat` new feature · `fix` bug fix · `docs` documentation · `refactor` restructure, no behaviour change ·
    `test` tests only · `chore` tooling/deps/config · `build` packaging/firmware build · `perf` performance · `style` formatting
  - Scopes (optional): `core`, `fsm`, `emg`, `vision`, `arbitration`, `dashboard`, `eval`, `firmware`, `xiao`
  - Examples: `feat(arbitration): add preference store` · `fix(vision): reset tracker on camera switch` ·
    `docs: update team plan`
