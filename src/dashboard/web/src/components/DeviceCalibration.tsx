import { send } from "../state/connect";
import { useDashboard } from "../state/store";

const CAPTURES = [
  ["r", "1. Rest", "Relax both muscles"],
  ["f", "2. Flexion", "Hold normal flexion"],
  ["e", "3. Extension", "Hold normal extension"],
  ["h", "4. High extension", "Hold a stronger extension"],
] as const;

export function DeviceCalibration() {
  const system = useDashboard((s) => s.system);
  const home = useDashboard((s) => s.fsm?.state === "HOME");
  const menu = useDashboard((s) => ["HOME", "ADAPTIVE", "FULL"].includes(s.fsm?.state ?? ""));
  const released = useDashboard((s) => s.held.length === 0);
  const link = useDashboard((s) => s.link);
  if (system?.controller !== "firmware") return null;
  const connected = link === "open" && system.hand_link.status === "connected";
  const setup = !!system.calibration_mode;
  const ready = connected && released && home && setup;
  const state = !connected ? "Firmware unavailable" : system.hand_link.armed ? "EMG armed"
    : system.hand_link.calibrated ? "Calibrated · relax to arm" : "EMG needs calibration";

  return (
    <section className="drawer-group" aria-label="Firmware EMG calibration">
      <h3 className="drawer-group-title">Firmware EMG calibration</h3>
      <p className="drawer-note" role="status">{state}</p>
      {!setup ? (
        <>
          <p className="drawer-note">Start calibration clears the previous calibration and pauses menu loading.</p>
          <button className="btn" disabled={!connected || !menu || !released}
            onClick={() => send({ type: "control", data: { action: "device_setup", enabled: true } })}>
            Start calibration
          </button>
        </>
      ) : (
        <>
          <p className="drawer-note">For each capture: 2 seconds to prepare, then hold for 4 seconds. Wait for the firmware DONE message before the next capture.</p>
          <div className="calibration-buttons">
            {CAPTURES.map(([command, label, instruction]) => (
              <button key={command} className="btn" disabled={!ready} title={instruction}
                onClick={() => send({ type: "control", data: { action: "device_command", command } })}>
                {label}
              </button>
            ))}
            <button className="btn btn-primary" disabled={!ready}
              onClick={() => send({ type: "control", data: { action: "device_command", command: "v" } })}>
              Validate calibration
            </button>
            <button className="btn" disabled={!ready}
              onClick={() => send({ type: "control", data: { action: "device_command", command: "x" } })}>
              Cancel capture
            </button>
          </div>
          <button className="btn" disabled={!ready}
            onClick={() => send({ type: "control", data: { action: "device_setup", enabled: false } })}>
            Resume dashboard
          </button>
        </>
      )}
      <p className="drawer-note calibration-log" aria-live="polite">{system.hand_link.calibration_log?.join("\n") || system.hand_link.calibration || system.hand_link.detail}</p>
      <p className="drawer-note">Keyboard remains available alongside EMG. Use E to return from a grip before calibration.</p>
    </section>
  );
}
