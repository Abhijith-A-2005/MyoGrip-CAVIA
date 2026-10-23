# CAVIA Dashboard

The live dashboard for MyoGrip CAVIA: wrist camera, target and confidence, the Adaptive and Full menus
side by side, the hand, and the EMG timeline. Other pages show each user's selection history and the
evaluation results.

It is a **mirror**: it shows what the CAVIA backend sends and never decides menus or FSM transitions.
The only things it sends back are keyboard EMG keys and experimenter controls.

## Run

```bash
cd src/dashboard/web
npm install          # first time only
npm run dev          # http://localhost:5173 (mock mode by default)
```

| Command | What it does |
|---|---|
| `npm run dev` | Dev server with hot reload. Uses mock data unless `?live=1` |
| `npm run build` | Typecheck and build into `web/dist/` (served by the FastAPI backend) |
| `npm run test:fsm` | Runs the shared FSM vectors (`tests/fsm/vectors.json`) against the mock FSM |
| `npx oxlint src` | Lint |

## Live mode (Python backend)

```bash
cd src/dashboard/web && npm run build      # the backend serves this build
cd ../../..                                 # repo root
pip install -e ".[dashboard]"
python -m cavia.server                      # http://127.0.0.1:8000
```

Options: `--port 8000`, `--host 0.0.0.0` (open from another device on the network), `--participant P01`,
`--condition C3_ADAPTIVE`. While developing the UI against the backend, run `npm run dev` and open
`http://localhost:5173/?live=1` instead (hot reload, same backend).

Vision on the dashboard:

```bash
python -m cavia.server --vision live                       # run objdet.py with the camera (needs ".[vision]")
python -m cavia.server --vision live --record-vision data/vision/recordings/mug.jsonl   # ...and record it
python -m cavia.server --replay data/vision/recordings/mug.jsonl                         # replay, no camera
python -m cavia.server --replay data/vision/samples/synthetic-cup-handle.jsonl           # synthetic sample
```

With `--vision live` the camera picture appears in the dashboard's viewfinder (the OpenCV window still
opens too). `--vision-script PATH` runs another script in place of `objdet.py`, for example a stand-in
that uses the same `publish_result` / `publish_frame` calls when no camera stack is installed.

Recordings hold tracker results only (no images) and replay at their original pace in a loop, so a
replay shows the overlays and target panel without a picture.
`data/vision/recordings/` is gitignored; `data/vision/samples/` holds a small synthetic file for testing.

The server runs the real arbitration engine and FSM controller (the one behind `python -m cavia --user 1`):
lock an object, and the Adaptive and Full menus, hand state and EMG timeline are live. Drive it with the
same keys as mock mode (`W` `S` `A` `D` `E`). The drawer's participant ID selects whose preference history
ranks the menu (`--db`, default `data/arbitration/demo.sqlite3`); every run writes a session log to
`--log-dir` (default `data/arbitration/sessions/`).

## Users

Each user (participant ID) has its own preference history, stored in the `--db` SQLite file (gitignored, so
histories stay on the laptop that recorded them). Click **User ▾** in the header to:

- switch users: allowed until a grip is confirmed; an unconfirmed menu is cleared and the next lock is
  ranked for the new user. During a grip, leave it (`E`) first;
- add a user with **+ New user** (letters, digits, `-` and `_`, up to 24 characters). The new user becomes
  the current one.

The list holds every registered user plus anyone found in the history (for example users `1` and `2`
from `python -m cavia --user 1`). Rejected requests show their reason in the list.

## History page

`#/history`, from the **History** tab. Pick a user to see:

- totals: selections, learned, share from the Adaptive menu, top suggestion taken, Full menu overrides;
- **What CAVIA has learned**: learned grips per object and region, the counts that rank the Adaptive menu;
- **Selections**: every confirmed grip, newest first, with the menu it came from (Adaptive rank or Full
  menu), the menu that was shown, and whether it was learned or cancelled.

It reads `GET /api/history?user=<id>` and refreshes when that user's counts change. Viewing a user here
does not switch the live user. Mock mode shows sample histories for users `1` and `2`.

Not yet in live mode: the Manual (C1) and Static (C2) conditions, which need support in the arbitration
engine, and the real hand (the Hand status stays red; the FSM is simulated from the keys).

## Mock mode

No backend needed: a scripted camera lock, the menus, and a TypeScript port of the reference FSM
(`src/state/mockFsm.ts`, kept identical to `src/keyboard_sim/fsm/machine.py` by `npm run test:fsm`).

| URL option | Effect |
|---|---|
| `?mock=1` / `?live=1` | Force mock data / the real backend (dev defaults to mock, a build to live) |
| `?backend=host:port` | Backend address for live mode (default: this host, port 8000) |
| `?policy=TOP_TWO` | Adaptive menu policy: `TOP_TWO`, `ONE_CONFIRM`, `FULL_COMPATIBLE`, `FULL_MENU` |
| `?camera=lost` | Show the camera failure state |
| `?participant=P03` | Starting user (mock users `1` and `2` come with sample history) |
| `?script=3:s,3.5:a:1.5` | Press keys automatically: `time:key[:hold seconds]`, comma-separated. Good for a hands-free demo |

The experimenter drawer's condition switch also changes the mock scenario (Manual, Static, Adaptive).

## Keys

| Key | In a menu | In a grip |
|---|---|---|
| `W` | Up (SE) | |
| `S` | Down (SF) | |
| `A` | Confirm (LF); keep holding to start closing | Hold to close |
| `D` | Full menu (LE) | Hold to open |
| `E` | Back to CAVIA Home (HE) | Leave the grip: controlled opening, then Full menu |
| `` ` `` | Show or hide the experimenter drawer | |
| `Esc` | Close the drawer | |

Same rules as the pygame simulator: one press is one gesture, a gesture pressed while another key is held
is ignored as `INVALID`, `A` and `D` together stop the hand, and losing window focus releases every key.

## Pages

- `#/` Live dashboard
- `#/history` Selection history per user
- `#/evaluation` Evaluation (shell; filled in after the pilot)

Hash routes, so the backend serves only `index.html` and never needs SPA fallback rules.

## Design

Composed once on a fixed **1920×1080 stage** and scaled to fit any window, so the projector and a
1366×768 laptop show the same layout. Theme tokens are in `web/src/theme/tokens.css` (colours sampled
from the reference poster). The focused panel (camera, Adaptive menu, Full menu or Hand) is a pure
function of the FSM state (`focusArea` in `web/src/labels.ts`), and a single light glides to it.

Fonts (Cinzel, Figtree) are installed from npm so the dashboard works without internet.
`prefers-reduced-motion` turns transitions off and hides the background particles.

## Layout of the code

```text
web/src/
├── App.tsx, LivePage.tsx, HistoryPage.tsx, EvaluationPage.tsx
├── components/   Stage, Atmosphere, FocusLight, Header, UserSwitcher, CameraPanel, TargetPanel,
│                 HandPanel, Menus, GripGlyph, EmgRibbon, ExperimenterDrawer, Panel
├── state/        store (latest snapshot), ws (backend), mock + mockFsm, keyboard, connect, ui
├── types/        messages.ts: TypeScript copy of the data contract
├── theme/        tokens.css, base.css
└── labels.ts     display names, policy subtitles, focus rule, moves-to-reach
web/tests/        fsm-vectors.test.ts
web/public/       favicon, mock camera frames
```

## Data contract

`ws://<host>:8000/ws`, `http://<host>:8000/video` (MJPEG) and `http://<host>:8000/api/history?user=<id>`. Message shapes are in
[`docs/interfaces.md`](../../docs/interfaces.md) section 9 and mirrored in `web/src/types/messages.ts`.
