import { CONDITION_LABEL } from "../labels";
import { useDashboard, type Link } from "../state/store";
import type { HealthStatus } from "../types/messages";
import "./Header.css";

type Tone = "good" | "warn" | "bad" | "idle";

const tone = (s: HealthStatus | undefined): Tone => {
  if (!s) return "idle";
  if (s === "live" || s === "ok" || s === "connected") return "good";
  if (s === "degraded") return "warn";
  return "bad";
};

const LINK_TEXT: Record<Link, [string, Tone]> = {
  open: ["Live data", "good"],
  mock: ["Mock data", "warn"],
  connecting: ["Connecting", "idle"],
  reconnecting: ["Reconnecting", "bad"],
};

function Status({ label, tone, detail }: { label: string; tone: Tone; detail?: string }) {
  return (
    <li className="status" data-tone={tone} title={detail}>
      <span className="status-dot" />
      {label}
    </li>
  );
}

export function Header() {
  const session = useDashboard((s) => s.session);
  const system = useDashboard((s) => s.system);
  const link = useDashboard((s) => s.link);

  const cam = system?.camera;
  const devCamera = cam?.source === "LAPTOP";
  const battery = system?.hand_link.battery_pct;

  return (
    <header className="hdr">
      <div className="hdr-brand">
        <h1 className="wordmark">MyoGrip Cavia</h1>
        <p className="hdr-tagline">Context-aware visual intent arbitration</p>
      </div>

      <div className="hdr-session" aria-label="Session">
        <span className="hdr-condition">{session ? CONDITION_LABEL[session.condition] : "No session"}</span>
        {session && (
          <span className="hdr-meta">
            <span>Participant <b>{session.participant}</b></span>
            <span>Trial <b className="num">{session.trial}</b></span>
          </span>
        )}
      </div>

      <ul className="hdr-status" aria-label="System status">
        <Status
          label={devCamera ? "Laptop camera" : "Camera"}
          tone={devCamera ? "warn" : tone(cam?.status)}
          detail={cam ? `${cam.source}, ${cam.fps.toFixed(1)} fps, ${cam.latency_ms} ms` : undefined}
        />
        <Status label="Vision" tone={tone(system?.vision.status)} detail={system?.vision.model} />
        <Status
          label="Hand"
          tone={tone(system?.hand_link.status)}
          detail={battery != null ? `Battery ${battery}%` : undefined}
        />
        <Status label={LINK_TEXT[link][0]} tone={LINK_TEXT[link][1]} />
      </ul>
    </header>
  );
}
