import { useEffect, useRef, useState } from "react";
import { clockText, CONDITION_LABEL, GRIP_LABEL, REST_TARGET_S, taskLabel } from "../labels";
import { send } from "../state/connect";
import { useRestSeconds } from "../state/rest";
import { useDashboard } from "../state/store";
import { setDrawer, useDrawer } from "../state/ui";
import type { Condition, TaskInfo } from "../types/messages";
import { DeviceCalibration } from "./DeviceCalibration";
import "./ExperimenterDrawer.css";

const CONDITIONS: Condition[] = ["C1_MANUAL", "C2_STATIC", "C3_ADAPTIVE"];
const NO_TASKS: TaskInfo[] = [];

export function ExperimenterDrawer() {
  const open = useDrawer();
  const session = useDashboard((s) => s.session);
  const users = useDashboard((s) => s.users);
  const notice = useDashboard((s) => s.notice);
  const taskMsg = useDashboard((s) => s.tasks);
  const tasks = taskMsg?.tasks ?? NO_TASKS;
  const restSeconds = useRestSeconds();
  const [taskId, setTaskId] = useState<string | null>(null);
  const [practice, setPractice] = useState(false);
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

  // Default to the first task once the list arrives; "free trial" stays a deliberate choice.
  useEffect(() => {
    if (taskId === null && tasks.length > 0) setTaskId(tasks[0].id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tasks.length]);

  const active = !!session?.trial_active;
  const resting = !!session?.rest_active;
  const restsDone = (session?.rest ?? 0) - (resting ? 1 : 0);
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

  const chosen = tasks.find((t) => t.id === taskId) ?? null;

  const startTrial = () => {
    send({ type: "control", data: { action: "start_trial", task_id: chosen?.id ?? null, practice } });
    setStatus(`Trial ${trial + 1} started${chosen ? `: ${chosen.id}` : ", free trial"}${practice ? " (practice)" : ""}.`);
  };

  const randomTask = () => {
    const others = tasks.filter((t) => t.id !== taskId);
    if (others.length) setTaskId(others[Math.floor(Math.random() * others.length)].id);
  };

  const startRest = () => {
    send({ type: "control", data: { action: "start_rest" } });
    setStatus("Rest started. Ask the participant to relax the hand.");
  };

  const endRest = () => {
    send({ type: "control", data: { action: "end_rest" } });
    setStatus(`Rest ended after ${clockText(restSeconds ?? 0)}.`);
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

        <DeviceCalibration />

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

          <button className="btn" onClick={applySession} disabled={active || resting || !changed}>
            Apply session
          </button>
          {(active || resting) && <p className="drawer-note">End the current {active ? "trial" : "rest"} to change the session.</p>}
        </section>

        <section className="drawer-group">
          <h3 className="drawer-group-title">
            Trial <span className="num">{active ? trial : trial + 1}</span>
            {active && <span className="drawer-rec">Recording</span>}
          </h3>
          {resting ? (
            <p className="drawer-note">Trials start again after the rest window.</p>
          ) : !active ? (
            <>
              <fieldset className="field">
                <legend className="field-label field-label-row">
                  Task
                  {tasks.length > 1 && (
                    <button type="button" className="drawer-link" onClick={randomTask}>
                      Random task
                    </button>
                  )}
                </legend>
                <div className="tasks" role="radiogroup">
                  {tasks.map((t) => (
                    <button
                      key={t.id}
                      type="button"
                      role="radio"
                      aria-checked={taskId === t.id}
                      className="task"
                      data-on={taskId === t.id || undefined}
                      onClick={() => setTaskId(t.id)}
                    >
                      <span className="task-id">{t.id}</span>
                      <span className="task-name">{taskLabel(t)}</span>
                      <span className="task-grip">{GRIP_LABEL[t.target_grip]}</span>
                    </button>
                  ))}
                  <button
                    type="button"
                    role="radio"
                    aria-checked={taskId === null}
                    className="task task-free"
                    data-on={taskId === null || undefined}
                    onClick={() => setTaskId(null)}
                  >
                    <span className="task-name">Free trial</span>
                    <span className="task-grip">No target grip</span>
                  </button>
                </div>
              </fieldset>
              <label className="check">
                <input type="checkbox" checked={practice} onChange={(e) => setPractice(e.target.checked)} />
                Practice trial <span>(excluded from the analysis)</span>
              </label>
              <button className="btn btn-primary" onClick={startTrial}>
                Start trial
              </button>
            </>
          ) : (
            <>
              <div className="task-now">
                {session?.task ? (
                  <>
                    <span className="task-now-label">
                      {session.practice ? "Practice: ask for" : "Ask for"}
                    </span>
                    <span className="task-now-grip">{GRIP_LABEL[session.task.target_grip]}</span>
                    <span className="task-now-target">
                      on the {taskLabel(session.task).toLowerCase()} <span className="num">({session.task.id})</span>
                    </span>
                  </>
                ) : (
                  <span className="task-now-label">Free trial{session?.practice ? ", practice" : ""}: no target grip</span>
                )}
              </div>
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

        <section className="drawer-group">
          <h3 className="drawer-group-title">
            Rest window {restsDone > 0 && <span className="num drawer-count">{restsDone} done</span>}
            {resting && <span className="drawer-resting">Resting</span>}
          </h3>
          {!resting ? (
            <>
              <button className="btn" onClick={startRest} disabled={active}>
                Start rest ({REST_TARGET_S} s)
              </button>
              <p className="drawer-note">
                {active ? "End the trial first. " : ""}Hand relaxed, no task: gestures detected now count as false activations.
              </p>
            </>
          ) : (
            <>
              <div className="rest-timer" data-done={(restSeconds ?? 0) >= REST_TARGET_S || undefined}>
                <span className="rest-clock num">{clockText(restSeconds ?? 0)}</span>
                <span className="rest-bar">
                  <span style={{ transform: `scaleX(${Math.min(1, (restSeconds ?? 0) / REST_TARGET_S)})` }} />
                </span>
                <span className="rest-cue">
                  {(restSeconds ?? 0) >= REST_TARGET_S ? `${REST_TARGET_S} s reached. End the rest.` : `Target ${REST_TARGET_S} s`}
                </span>
              </div>
              <button className="btn btn-primary" onClick={endRest}>
                End rest
              </button>
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
