import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { useDashboard, type EmgEntry } from "../state/store";
import type { Activity, EmgEvent, FsmState } from "../types/messages";
import "./EmgRibbon.css";

const WINDOW_S = 15;
const ACTUATION: FsmState[] = ["CLOSING", "HOLDING", "OPENING"];

const EVENT_MEANING: Record<EmgEvent, string> = {
  SF: "Next",
  SE: "Previous",
  LF: "Confirm",
  LE: "Full menu",
  HE: "Back",
  REST: "Rest",
  INVALID: "Ignored",
};

type Span = { kind: "flex" | "ext"; from: number; to: number };

/** Sustained activity as time spans, rebuilt from the activity-change messages. */
function activitySpans(emg: EmgEntry[], now: number): Span[] {
  const spans: Span[] = [];
  let open: { kind: Span["kind"]; from: number } | null = null;
  for (const e of emg) {
    if (!e.activity) continue;
    if (open) spans.push({ ...open, to: e.at });
    open = e.activity === "FLEX_ACTIVE" ? { kind: "flex", from: e.at } : e.activity === "EXT_ACTIVE" ? { kind: "ext", from: e.at } : null;
  }
  if (open) spans.push({ ...open, to: now });
  return spans;
}

function lastActivity(emg: EmgEntry[]): Activity {
  for (let i = emg.length - 1; i >= 0; i--) if (emg[i].activity) return emg[i].activity!;
  return "REST";
}

/**
 * Re-render at ~30 fps so the timeline scrolls smoothly. The loop stops itself once the newest
 * entry has scrolled off and no activity is ongoing, so an idle ribbon costs nothing; any new
 * entry restarts it. requestAnimationFrame also pauses when the tab is hidden.
 */
function useNow(latest: number, active: boolean) {
  const [now, setNow] = useState(() => performance.now());
  useEffect(() => {
    let raf = 0;
    let last = 0;
    const tick = (t: number) => {
      if (t - last > 33) {
        last = t;
        setNow(t);
      }
      if (active || t - latest < (WINDOW_S + 1) * 1000) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [latest, active]);
  return now;
}

const CHIP_GAP = 6;
/** Rough chip widths at 14px Figtree; the newest chip also shows the meaning. */
const chipWidth = (event: EmgEvent, withMeaning: boolean) =>
  24 + event.length * 8.6 + (withMeaning ? EVENT_MEANING[event].length * 7.6 + 8 : 0);

/**
 * Place chips at their time, newest first, pushing older chips left so they never overlap.
 * Returns the distance of each chip's centre from the right edge, in px.
 */
function layoutChips(events: EmgEntry[], width: number, age: (at: number) => number) {
  const placed: { e: EmgEntry; right: number; wide: boolean }[] = [];
  // Left edge of the previously placed (newer) chip, from the right; starts so the newest chip fits fully.
  let edge = -CHIP_GAP;
  [...events].reverse().forEach((e, i) => {
    const wide = i === 0;
    const w = chipWidth(e.event!, wide);
    const natural = age(e.at) * width;
    const right = Math.max(natural, edge + CHIP_GAP + w / 2);
    placed.push({ e, right, wide });
    edge = right + w / 2;
  });
  return placed;
}

function useWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(1000);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setWidth(el.offsetWidth));
    ro.observe(el);
    setWidth(el.offsetWidth);
    return () => ro.disconnect();
  }, []);
  return { ref, width };
}

function Meter({ label, on, kind }: { label: string; on: boolean; kind: "flex" | "ext" }) {
  return (
    <div className="meter" data-on={on || undefined} data-kind={kind}>
      <span className="meter-bar" />
      <span className="meter-label">{label}</span>
    </div>
  );
}

const PAD: { key: string; menu: string; move?: string }[] = [
  { key: "w", menu: "Up" },
  { key: "e", menu: "Back", move: "Release" },
  { key: "a", menu: "Confirm", move: "Close" },
  { key: "s", menu: "Down" },
  { key: "d", menu: "Full menu", move: "Open" },
];

function KeyPad({ held, moving }: { held: string[]; moving: boolean }) {
  return (
    <div className="pad" aria-label="Keyboard EMG emulator">
      {PAD.map(({ key, menu, move }) => (
        <div key={key} className={`pad-key pad-${key}`} data-held={held.includes(key) || undefined}>
          <span className="pad-cap">{key.toUpperCase()}</span>
          <span className="pad-label">{moving && move ? move : moving ? "" : menu}</span>
        </div>
      ))}
    </div>
  );
}

export function EmgRibbon() {
  const emg = useDashboard((s) => s.emg);
  const held = useDashboard((s) => s.held);
  const firmware = useDashboard((s) => s.system?.controller === "firmware");
  const keyboardReady = useDashboard((s) => s.system?.keyboard_ready);
  const state = useDashboard((s) => s.fsm?.state ?? "HOME");
  const latest = emg.length ? emg[emg.length - 1].at : -Infinity;
  const activity = lastActivity(emg);
  const now = useNow(latest, activity !== "REST");
  const { ref: timeline, width } = useWidth<HTMLDivElement>();

  const moving = ACTUATION.includes(state);
  // Position on the timeline: 0 at "now" (right edge) to 1 at WINDOW_S ago (left edge).
  const age = (at: number) => (now - at) / 1000 / WINDOW_S;
  // In a grip the FSM only acts on HE; other discrete gestures there are shown as activity bars.
  const shown = (e: EmgEntry) => !e.moving || e.event === "HE" || e.event === "INVALID";
  const events = emg.filter((e) => e.event && e.event !== "REST" && shown(e) && age(e.at) <= 1);
  const spans = activitySpans(emg, now).filter((s) => age(s.to) <= 1);

  return (
    <footer className="ribbon" aria-label="EMG events">
      <div className="ribbon-left">
        <p className="ribbon-caption">{firmware ? "EMG + keys" : "Keyboard"}</p>
        <Meter label="Flexor" kind="flex" on={moving && (activity === "FLEX_ACTIVE" || activity === "INVALID")} />
        <Meter label="Extensor" kind="ext" on={moving && (activity === "EXT_ACTIVE" || activity === "INVALID")} />
      </div>

      <div className="timeline" ref={timeline}>
        <span className="timeline-now">now</span>
        {spans.map((s, i) => {
          const right = Math.max(0, age(s.to)) * 100;
          const left = Math.min(1, age(s.from)) * 100;
          return (
            <span
              key={`${s.kind}-${s.from}-${i}`}
              className="span"
              data-kind={s.kind}
              style={{ right: `${right}%`, width: `${Math.max(0.4, left - right)}%` }}
            />
          );
        })}
        {layoutChips(events, width, age).map(({ e, right, wide }) => {
          const a = right / width;
          if (a > 1.05) return null;
          return (
            <span
              key={e.seq}
              className="evt"
              data-event={e.event}
              data-wide={wide || undefined}
              style={{ right, opacity: Math.max(0, 1 - Math.max(0, a - 0.6) / 0.4) }}
              title={`${e.event} ${EVENT_MEANING[e.event!]}`}
            >
              <b>{e.event}</b>
              {wide && EVENT_MEANING[e.event!]}
            </span>
          );
        })}
        {events.length === 0 && spans.length === 0 && (
          <span className="timeline-empty">Gestures appear here as they are detected</span>
        )}
      </div>

      <div title={firmware && !keyboardReady ? "Waiting for the firmware keyboard handshake" : "W/S navigate, A confirm/close, D full/open, E back/release"}>
        <KeyPad held={held} moving={moving} />
      </div>
    </footer>
  );
}
