import { useEffect, useRef, useState } from "react";
import { CONDITION_LABEL } from "../labels";
import { send } from "../state/connect";
import { useDashboard } from "../state/store";
import { setDrawer, useDrawer } from "../state/ui";
import type { Condition } from "../types/messages";
import "./ExperimenterDrawer.css";

const CONDITIONS: Condition[] = ["C1_MANUAL", "C2_STATIC", "C3_ADAPTIVE"];

export function ExperimenterDrawer() {
  const open = useDrawer();
  const session = useDashboard((s) => s.session);
  const users = useDashboard((s) => s.users);
  const notice = useDashboard((s) => s.notice);
  const [participant, setParticipant] = useState("P01");
  const [condition, setCondition] = useState<Condition>("C3_ADAPTIVE");
  const [notes, setNotes] = useState("");
  const [status, setStatus] = useState("");
  const panel = useRef<HTMLDivElement>(null);

  // Start from the live session each time the drawer opens.
  useEffect(() => {
    if (!open) return;
    if (session) {
      setParticipant(session.participant);
      setCondition(session.condition);
    }
    setStatus("");
    // Focus the first useful control, not the close button.
    panel.current?.querySelector<HTMLElement>("input:not(:disabled), textarea, .btn-primary")?.focus();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  // A rejected control replaces the optimistic status line.
  useEffect(() => {
    if (open && notice) setStatus(notice.message);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [notice]);

  const active = !!session?.trial_active;
  const trial = session?.trial ?? 0;
  const changed = !!session && (participant !== session.participant || condition !== session.condition);

  const applySession = () => {
    const id = participant.trim().toUpperCase();
    if (!id) {
      setStatus("Enter a participant ID first.");
      return;
    }
    send({ type: "control", data: { action: "set_session", participant: id, condition } });
    setStatus(`Session set: ${id}, ${CONDITION_LABEL[condition]}.`);
  };

  const startTrial = () => {
    send({ type: "control", data: { action: "start_trial" } });
    setStatus(`Trial ${trial + 1} started.`);
  };

  const endTrial = (grasp_success: boolean) => {
    send({ type: "control", data: { action: "end_trial", grasp_success, notes: notes.trim() } });
    setStatus(`Trial ${trial} ended: grasp ${grasp_success ? "succeeded" : "failed"}.`);
    setNotes("");
  };

  return (
    <>
      <div className="drawer-scrim" data-open={open || undefined} onClick={() => setDrawer(false)} />
      <aside
        className="drawer"
        data-open={open || undefined}
        aria-hidden={!open}
        aria-label="Experimenter controls"
        ref={panel}
        inert={!open}
      >
        <header className="drawer-head">
          <h2 className="drawer-title">Experimenter</h2>
          <button className="drawer-close" onClick={() => setDrawer(false)} aria-label="Close experimenter controls">
            <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden>
              <path d="M6 6l12 12M18 6L6 18" />
            </svg>
          </button>
        </header>

        <section className="drawer-group">
          <h3 className="drawer-group-title">Session</h3>
          <label className="field">
            <span className="field-label">Participant</span>
            <input
              className="field-input"
              list="participants"
              value={participant}
              onChange={(e) => setParticipant(e.target.value)}
              disabled={active}
              spellCheck={false}
            />
            <datalist id="participants">
              {users?.users.map((u) => (
                <option key={u.user} value={u.user} />
              ))}
            </datalist>
          </label>

          <fieldset className="field" disabled={active}>
            <legend className="field-label">Condition</legend>
            <div className="segmented" role="radiogroup">
              {CONDITIONS.map((c) => (
                <button
                  key={c}
                  type="button"
                  role="radio"
                  aria-checked={condition === c}
                  className="segment"
                  data-on={condition === c || undefined}
                  onClick={() => setCondition(c)}
                >
                  {CONDITION_LABEL[c]}
                </button>
              ))}
            </div>
          </fieldset>

          <button className="btn" onClick={applySession} disabled={active || !changed}>
            Apply session
          </button>
          {active && <p className="drawer-note">End the current trial to change the session.</p>}
        </section>

        <section className="drawer-group">
          <h3 className="drawer-group-title">
            Trial <span className="num">{active ? trial : trial + 1}</span>
            {active && <span className="drawer-rec">Recording</span>}
          </h3>
          {!active ? (
            <button className="btn btn-primary" onClick={startTrial}>
              Start trial
            </button>
          ) : (
            <>
              <label className="field">
                <span className="field-label">Notes</span>
                <textarea
                  className="field-input field-notes"
                  value={notes}
                  onChange={(e) => setNotes(e.target.value)}
                  placeholder="Anything unusual in this trial"
                  rows={3}
                />
              </label>
              <div className="drawer-outcome">
                <button className="btn btn-primary" onClick={() => endTrial(true)}>
                  Grasp succeeded
                </button>
                <button className="btn btn-danger" onClick={() => endTrial(false)}>
                  Grasp failed
                </button>
              </div>
            </>
          )}
        </section>

        <p className="drawer-status" role="status" aria-live="polite">
          {status}
        </p>
        <p className="drawer-hint">
          Press <kbd>`</kbd> to show or hide this panel.
        </p>
      </aside>
    </>
  );
}
