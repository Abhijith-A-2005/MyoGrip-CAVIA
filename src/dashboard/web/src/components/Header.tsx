import { CONDITION_LABEL } from "../labels";
import { useDashboard, type Link } from "../state/store";
import { hrefOf, navigate, toggleDrawer, useRoute, type Route } from "../state/ui";
import type { HealthStatus } from "../types/messages";
import { UserSwitcher } from "./UserSwitcher";
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

function Tab({ route, current, children }: { route: Route; current: Route; children: string }) {
  return (
    <a
      href={hrefOf(route)}
      className="hdr-tab"
      aria-current={route === current ? "page" : undefined}
      onClick={(e) => {
        e.preventDefault();
        navigate(route);
      }}
    >
      {children}
    </a>
  );
}

export function Header() {
  const session = useDashboard((s) => s.session);
  const system = useDashboard((s) => s.system);
  const link = useDashboard((s) => s.link);
  const route = useRoute();

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
            <UserSwitcher />
            {session.trial > 0 ? (
              <span>Trial <b className="num">{session.trial}</b></span>
            ) : (
              <span>No trial yet</span>
            )}
            {session.trial_active && <span className="hdr-rec">Recording</span>}
          </span>
        )}
      </div>

      <div className="hdr-right">
        <nav className="hdr-tabs" aria-label="Pages">
          <Tab route="live" current={route}>Live</Tab>
          <Tab route="history" current={route}>History</Tab>
          <Tab route="evaluation" current={route}>Evaluation</Tab>
        </nav>
        <ul className="hdr-status" aria-label="System status">
          <Status
            label={devCamera ? "Laptop camera" : "Camera"}
            tone={devCamera ? "warn" : tone(cam?.status)}
            detail={cam ? `${cam.source}, ${cam.fps.toFixed(1)} fps${cam.latency_ms > 0 ? `, ${cam.latency_ms} ms` : ""}` : undefined}
          />
          <Status label="Vision" tone={tone(system?.vision.status)} detail={system?.vision.model} />
          <Status
            label="Hand"
            tone={tone(system?.hand_link.status)}
            detail={battery != null ? `Battery ${battery}%` : undefined}
          />
          <Status label={LINK_TEXT[link][0]} tone={LINK_TEXT[link][1]} />
        </ul>
        <button className="hdr-gear" onClick={toggleDrawer} aria-label="Experimenter controls" title="Experimenter controls (`)">
          <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden>
            <path d="M4 7h10M18 7h2M4 17h2M10 17h10" />
            <circle cx="16" cy="7" r="2" />
            <circle cx="8" cy="17" r="2" />
          </svg>
        </button>
      </div>
    </header>
  );
}
