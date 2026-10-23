import { useEffect, useRef, useState, type FormEvent } from "react";
import { ago } from "../labels";
import { send } from "../state/connect";
import { useDashboard } from "../state/store";
import type { UserInfo } from "../types/messages";
import "./UserSwitcher.css";

/** Same rule as the backend (cavia.server.session.participant_id). */
const PARTICIPANT_ID = /^[A-Z0-9][A-Z0-9_-]{0,23}$/;

function userMeta(u: UserInfo): string {
  if (u.selections === 0) return "No history yet";
  const learned = `${u.accepted} learned`;
  return u.last_used ? `${learned}, ${ago(u.last_used)}` : learned;
}

export function UserSwitcher() {
  const session = useDashboard((s) => s.session);
  const users = useDashboard((s) => s.users);
  const actuating = useDashboard((s) => ["CLOSING", "HOLDING", "OPENING"].includes(s.fsm?.state ?? "HOME"));
  const notice = useDashboard((s) => s.notice);
  const [open, setOpen] = useState(false);
  const [adding, setAdding] = useState(false);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState("");
  const noticeBase = useRef(0);
  const root = useRef<HTMLDivElement>(null);

  const current = users?.current ?? session?.participant ?? "";
  const list = users?.users ?? (current ? [{ user: current, created_at: null, selections: 0, accepted: 0, last_used: null }] : []);
  const locked = session?.trial_active
    ? "End the trial to switch users"
    : actuating
      ? "Leave the grip (E) to switch users"
      : "";

  // A rejection from the backend after one of our requests.
  useEffect(() => {
    if (notice && notice.seq > noticeBase.current && (notice.action === "set_session" || notice.action === "add_user")) {
      setError(notice.message);
    }
  }, [notice]);

  useEffect(() => {
    if (!open) return;
    const onDown = (ev: MouseEvent) => {
      if (!root.current?.contains(ev.target as Node)) setOpen(false);
    };
    const onKey = (ev: KeyboardEvent) => ev.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDown);
    window.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      window.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const toggle = () => {
    setOpen(!open);
    setAdding(false);
    setDraft("");
    setError("");
  };

  const request = () => {
    noticeBase.current = notice?.seq ?? 0;
    setError("");
  };

  const switchTo = (user: string) => {
    if (!session || user === current) return;
    request();
    send({ type: "control", data: { action: "set_session", participant: user, condition: session.condition } });
  };

  const add = (ev: FormEvent) => {
    ev.preventDefault();
    const id = draft.trim().toUpperCase();
    if (!PARTICIPANT_ID.test(id)) {
      setError("Use letters, digits, - or _ (up to 24 characters).");
      return;
    }
    request();
    if (!list.some((u) => u.user === id)) send({ type: "control", data: { action: "add_user", user: id } });
    if (!locked && session) {
      send({ type: "control", data: { action: "set_session", participant: id, condition: session.condition } });
    }
    setAdding(false);
    setDraft("");
  };

  return (
    <div className="usw" ref={root}>
      <button
        className="usw-btn"
        onClick={toggle}
        aria-haspopup="dialog"
        aria-expanded={open}
        disabled={!session}
        title="Switch user"
      >
        User <b>{current || "none"}</b>
        <svg viewBox="0 0 24 24" width="14" height="14" aria-hidden>
          <path d="M6 9l6 6 6-6" />
        </svg>
      </button>

      {open && (
        <div className="usw-pop" role="dialog" aria-label="Switch user">
          <p className="usw-title">Preference profiles</p>
          <ul className="usw-list">
            {list.map((u) => (
              <li key={u.user}>
                <button
                  className="usw-row"
                  data-current={u.user === current || undefined}
                  onClick={() => switchTo(u.user)}
                  disabled={!!locked && u.user !== current}
                >
                  <span className="usw-id">{u.user}</span>
                  <span className="usw-meta">{userMeta(u)}</span>
                  {u.user === current && (
                    <svg className="usw-check" viewBox="0 0 24 24" width="18" height="18" aria-label="Current user">
                      <path d="M5 12.5l4.5 4.5L19 7.5" />
                    </svg>
                  )}
                </button>
              </li>
            ))}
          </ul>

          {adding ? (
            <form className="usw-add" onSubmit={add}>
              <input
                className="usw-input"
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                placeholder="New ID, e.g. P03"
                maxLength={24}
                spellCheck={false}
                autoFocus
              />
              <button className="usw-go" type="submit" disabled={!draft.trim()}>
                Add
              </button>
            </form>
          ) : (
            <button className="usw-new" onClick={() => setAdding(true)}>
              <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden>
                <path d="M12 5v14M5 12h14" />
              </svg>
              New user
            </button>
          )}

          <p className="usw-note" role="status" aria-live="polite" data-error={error ? true : undefined}>
            {error || locked || "Whose history ranks the menu. Switching clears an unconfirmed menu."}
          </p>
        </div>
      )}
    </div>
  );
}
