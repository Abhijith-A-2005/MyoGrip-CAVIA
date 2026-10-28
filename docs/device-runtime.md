# Board-backed dashboard runtime checkpoint

`DeviceDashboardRuntime` connects the existing arbitration engine to the shared-input
firmware. It publishes the existing Hub message shapes for menus, FSM state and EMG
activity. Dashboard startup and browser controls will select this runtime in the
following checkpoint.

## Verify this checkpoint

```powershell
python -m pytest tests/server/test_device_runtime.py tests/server/test_device_link.py -q
python -m cavia.server.device_runtime --port COM14
```

The hardware check uses an in-memory preference database and one synthetic locked
`cup/handle` context. It sends an actual menu to the board and requires an exact
acknowledged menu ID and grip order. It is not a camera test. Close other serial
viewers first and keep muscles relaxed during this menu-link check.

Expected hardware result:

```text
PASS: dashboard vision menu acknowledged by firmware
```

## Runtime behavior

- The runtime owns its SQLite store on one thread. Browser key/control requests enter
  a queue; the vision feed polls on that same runtime thread.
- `tick(dt)` consumes board snapshots before controls or vision. It never runs a
  local hand FSM or integrates grip progress.
- Menus are shown after their IDs and copied grip lists match firmware telemetry.
  Refreshes preserve grip identity and the board's Full Menu state.
- Confirmed actuation pauses vision until the board returns Home. Lost/stale vision
  keeps the last acknowledged menu; it never resets the board automatically.
- Each USB connection/board boot starts a newer keyboard session with a released
  sequence-1 handshake. Held-mask heartbeats run every 100 ms. Browser state updates
  may release keys but cannot recreate a press after disconnect or timeout.
- The browser must refresh its held-key state within 350 ms. Calibration controls
  require firmware Home and released keys.
- Only an unambiguous observed device-source LF confirmation of a known acknowledged
  menu can create pending EMG preference feedback. Eligibility requires at least
  500 subsequent board samples and observed progress of at least 0.2. This records
  preference eligibility, not physical grasp success. Stale/reset/early-return or
  ambiguous interactions are cancelled; keyboard assistance excludes or revokes
  the affected interaction. Existing preference history still ranks proposals.
- Reattaching to an unknown board menu displays its actual grips without inventing
  an object context or a confirmation history.

Call `open()`/`tick()`/`close()` on one thread for tests and diagnostics, or use
`start()`/`stop()` for the runtime worker. Supply a `DeviceLink`, `Hub`, `Session`,
preference database path and optional vision feed/pause callback.
