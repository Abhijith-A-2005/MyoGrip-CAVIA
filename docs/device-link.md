# USB device link checkpoint

`cavia.server.device_link.DeviceLink` owns one USB connection to the shared-input
firmware. The dashboard runtime will consume this transport in the next integration
checkpoint. The connection check below only reads telemetry.

```powershell
python -m pip install -e ".[device]" pytest
python -m pytest tests/server/test_device_link.py -q
python -m cavia.server.device_link --port COM14
```

Close the firmware monitor and other serial viewers before opening the same port.
A successful hardware check prints:

```text
PASS: dashboard serial link receives advancing firmware state
```

## Consumer API

- Construct `DeviceLink(port, baud=115200)` and call `start()` once.
- `status()` reports `connected`, `stale` or `disconnected`, plus calibration status.
- `drain()` returns validated board snapshots in arrival order. Treat these as read-only.
- `menu_line(snapshot, proposal, preserve=False)` encodes a bounded menu packet.
- `next_keyboard_session(snapshot)` chooses a newer session within the current boot.
- `keyboard_line(snapshot, session, sequence, mask)` encodes a held-key packet.
- `send(line)` queues a command only while the link has fresh telemetry.
- Call `close()` when shutting down.

The keyboard session must begin with sequence 1 and mask 0. Refresh a held mask
at 100 ms intervals; the board expires it after 400 ms. A timeout requires a new
release packet before another press. The transport does not generate heartbeats
or replay user input itself.

## Freshness and recovery

The accepted schema is `MGSTATE` version 1, wire version 3, keyboard wire version 2.
The parser checks finite progress, grip lists, state consistency, keyboard state and
integer bounds. Incomplete or incompatible frames are discarded without changing
the reported FSM state.

After connection or board reset, at least two valid snapshots with an advancing
sample counter are required. Both arrival and counter advancement must remain
less than 1.5 seconds old. Duplicate snapshots cannot keep a frozen board fresh.
Backward counters are discarded; normal uint32 counter wrap is accepted.

The worker retries failed connections every 0.5 seconds. Disconnect and board-boot
changes clear queued commands. Every queued command also carries the connection
epoch and board boot ID and expires after 250 ms. Old commands are dropped rather
than retransmitted. Command writes are bounded by a 300 ms serial write timeout.
