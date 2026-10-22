import { objectLabel, regionLabel, STAND_IN } from "../labels";
import { useDashboard } from "../state/store";
import "./TargetPanel.css";

/** Same thresholds as the menu policy (PolicyConfig.low_vision / shortcut_vision). */
function band(conf: number): { name: string; tone: "low" | "mid" | "high" } {
  if (conf >= 0.8) return { name: "High", tone: "high" };
  if (conf >= 0.6) return { name: "Moderate", tone: "mid" };
  return { name: "Low", tone: "low" };
}

const R = 58;
const C = 2 * Math.PI * R;

function ConfidenceRing({ value, active }: { value: number; active: boolean }) {
  const b = band(value);
  return (
    <div className="ring" data-tone={active ? b.tone : "low"}>
      <svg viewBox="0 0 140 140" aria-hidden>
        <circle className="ring-track" cx="70" cy="70" r={R} />
        <circle
          className="ring-value"
          cx="70"
          cy="70"
          r={R}
          strokeDasharray={C}
          strokeDashoffset={C * (1 - (active ? value : 0))}
        />
        {/* Policy thresholds as ticks on the track. */}
        {[0.6, 0.8].map((t) => (
          <line key={t} className="ring-tick" x1="121" y1="70" x2="135" y2="70" transform={`rotate(${t * 360} 70 70)`} />
        ))}
      </svg>
      <div className="ring-label">
        <span className="ring-pct num" data-empty={!active || undefined}>{active ? Math.round(value * 100) : "--"}</span>
        <span className="ring-band">{active ? b.name : "No region"}</span>
      </div>
    </div>
  );
}

function Evidence({ label, value, active }: { label: string; value: number; active: boolean }) {
  const pct = active ? Math.round(value * 100) : 0;
  return (
    <div className="ev">
      <span className="ev-label">{label}</span>
      <span className="ev-track">
        <span className="ev-fill" style={{ transform: `scaleX(${pct / 100})` }} />
      </span>
      <span className="ev-value num">{active ? `${pct}%` : ""}</span>
    </div>
  );
}

const TRACK_TEXT = {
  NO_OBJECT: "Point the wrist camera at an object",
  SEARCHING: "Holding the reticle steady",
  LOCKED: "Region locked",
  LOST: "Lost the object, hold steady",
} as const;

export function TargetPanel() {
  const v = useDashboard((s) => s.vision);
  const active = !!v && v.state !== "NO_OBJECT";
  const locked = v?.state === "LOCKED";

  return (
    <section className="target" data-area="context" data-locked={locked || undefined} aria-label="Target">
      <p className="target-caption">Target</p>

      <div className="target-main">
        <div className="target-names">
          <h2 className="target-object" data-empty={!active || undefined}>{active ? objectLabel(v.object) : "Nothing in view"}</h2>
          <p className="target-region">{active && v.region ? regionLabel(v.region) : " "}</p>
          <p className="target-track">
            {TRACK_TEXT[v?.state ?? "NO_OBJECT"]}
            {active && v.object && STAND_IN[v.object] ? `, ${STAND_IN[v.object]}` : ""}
          </p>
        </div>
        <ConfidenceRing value={v?.region_confidence ?? 0} active={active} />
      </div>

      <div className="target-evidence">
        <Evidence label="Detection" value={v?.det_conf ?? 0} active={active} />
        <Evidence label="On target" value={v?.reticle_score ?? 0} active={active} />
        <Evidence label="Stability" value={v?.stability ?? 0} active={active} />
      </div>
    </section>
  );
}
