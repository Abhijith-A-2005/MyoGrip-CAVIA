import { GRIP_LABEL, STATE_LABEL } from "../labels";
import { useDashboard } from "../state/store";
import type { FsmMsg, FsmState } from "../types/messages";
import { GripGlyph } from "./GripGlyph";
import "./HandPanel.css";

const MENU_STATES: FsmState[] = ["HOME", "ADAPTIVE", "FULL"];
const MOVE_STATES: FsmState[] = ["CLOSING", "HOLDING", "OPENING"];

function instruction(fsm: FsmMsg | null): { text: string; tone?: "notice" | "warn" } {
  if (!fsm) return { text: "Waiting for the hand controller" };
  if (fsm.returning) return { text: "Opening to release, then Full Menu", tone: "notice" };
  if (fsm.wait_release) return { text: "Stopped. Relax both muscles to continue", tone: "warn" };
  switch (fsm.state) {
    case "HOME":
      return { text: "Waiting for a menu" };
    case "ADAPTIVE":
    case "FULL":
      return { text: "Hold a long flex on a grip to start closing" };
    case "CLOSING":
      return { text: "Flexing: closing at constant speed" };
    case "HOLDING":
      return { text: "Relaxed: holding. Flex to close, extend to open" };
    case "OPENING":
      return { text: "Extending: opening at constant speed" };
  }
}

function Rail({ state }: { state: FsmState }) {
  const step = (s: FsmState) => (
    <li key={s} className="rail-step" data-state={s} data-current={s === state || undefined}>
      <span className="rail-dot" />
      {STATE_LABEL[s]}
    </li>
  );
  return (
    <ol className="rail" aria-label="Hand state">
      {MENU_STATES.map(step)}
      <li className="rail-gap" aria-hidden />
      {MOVE_STATES.map(step)}
    </ol>
  );
}

export function HandPanel({ focused }: { focused: boolean }) {
  const fsm = useDashboard((s) => s.fsm);
  const state = fsm?.state ?? "HOME";
  const progress = fsm?.grip_progress ?? 0;
  const pct = Math.round(progress * 100);
  const grip = fsm?.active_grip ?? null;
  const moving = MOVE_STATES.includes(state);
  const say = instruction(fsm);

  return (
    <section
      className="hand"
      data-area="hand"
      data-state={state}
      data-focused={focused || undefined}
      data-moving={moving || undefined}
      aria-label="Hand"
    >
      <p className="hand-caption">Hand</p>

      <div className="hand-main">
        <div className="hand-column" aria-label={`Grip progress ${pct}%`}>
          <div className="hand-column-track">
            {[0.25, 0.5, 0.75].map((t) => (
              <span key={t} className="hand-tick" style={{ bottom: `${t * 100}%` }} />
            ))}
            <div className="hand-column-fill" style={{ transform: `scaleY(${progress})` }} />
            <div className="hand-meniscus" style={{ bottom: `${progress * 100}%` }} />
          </div>
          <span className="hand-column-end hand-column-top">Closed</span>
          <span className="hand-column-end hand-column-bottom">Open</span>
        </div>

        <div className="hand-readout">
          <p className="hand-state">{STATE_LABEL[state]}</p>
          <p className="hand-pct num">
            {pct}
            <span>%</span>
          </p>
          <div className="hand-grip">
            {grip ? (
              <>
                <GripGlyph grip={grip} size={44} className="hand-grip-glyph" />
                <span>
                  <span className="hand-grip-name">{GRIP_LABEL[grip]}</span>
                  <span className="hand-grip-from">
                    from the {fsm?.menu_kind === "FULL" ? "full" : "adaptive"} menu
                  </span>
                </span>
              </>
            ) : (
              <span className="hand-grip-none">No grip confirmed</span>
            )}
          </div>
          <p className="hand-say" data-tone={say.tone}>
            {say.text}
          </p>
        </div>
      </div>

      <Rail state={state} />
    </section>
  );
}
