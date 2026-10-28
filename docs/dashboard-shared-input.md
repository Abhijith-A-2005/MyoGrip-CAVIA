# Dashboard with firmware EMG and keyboard

Close other serial monitors and use the flashed shared-input firmware. No new
firmware build is required for this checkpoint.

```powershell
python -m pytest tests/server -q
npm --prefix src/dashboard/web run build
python -m cavia.server --device-port COM14 --user 1
```

The browser at http://127.0.0.1:8000 shows **Firmware FSM · EMG + keyboard**.
Menus, selected grip, return state and progress come from advancing board snapshots.
The keyboard remains active: W/S navigate, A confirms/closes, D opens the Full
Menu/opens the grip, E backs out/releases. Heartbeats preserve a held key while
this browser remains active. Blur, hidden tabs, socket loss and missing heartbeats
release keys. Another idle viewer does not clear the controlling browser's keys.
A reconnect requires a new physical press; held-state heartbeats never add keys.

## Calibrate from the browser

Open **Experimenter controls** (top-right). Return from any grip first using E or
high extension. With all keys released, click **Start calibration**. This explicitly
cancels the old calibration, returns the firmware to Home, and holds menu loading
until **Resume dashboard**. It does not restart calibration on normal startup.

Click the four capture buttons in order. Each has a 2-second preparation phase
and a 4-second capture. The latest actual firmware calibration message appears
below the buttons. Wait for `REST DONE`, `FLEXION DONE`, `EXTENSION DONE`, or `HIGH_EXTENSION DONE` before starting the next capture:

1. Rest: relax both muscles throughout capture.
2. Flexion: hold normal flexion.
3. Extension: hold normal extension.
4. High extension: hold a stronger extension.

Click **Validate calibration**. Continue only when the displayed status is
**Calibrated · relax to arm** or **EMG armed**. Firmware rejection messages remain
visible; a button click alone does not imply success. If validation rejects weak
or overlapping references, repeat the captures. Click **Resume dashboard**, relax,
and wait for **EMG armed**. Present an object to vision to obtain a menu.

Use short flexion/extension for next/previous, long flexion to confirm, long
extension for Full Menu and high extension to release/back. During actuation,
flexion closes, extension opens and rest holds. Keyboard can assist at any time;
keyboard-assisted choices do not update real-EMG preference learning.

For a repeatable first browser test without running the camera model, use:

```powershell
python -m cavia.server --device-port COM14 --replay data/vision/samples/synthetic-cup-handle.jsonl --user 1
```

This replays only vision (cup/handle); EMG and keyboard still reach the actual
board. Stop this server before launching the live-camera command.

Omit `--device-port` to use the existing keyboard simulation with no firmware.
This checkpoint keeps that explicit choice. Automatic offline fallback and
handover when a configured board disappears are the next checkpoint. Until then,
a configured board that goes stale displays its last reported state with a
warning; there is no local progress animation pretending to be firmware.
