import { useSyncExternalStore } from "react";
import type { EmgMsg, ServerMessage, Snapshot } from "../types/messages";

export type Link = "connecting" | "open" | "reconnecting" | "mock";

/**
 * `at`: local arrival time (performance.now), so the ribbon is independent of the backend clock.
 * `moving`: the hand was in actuation when the gesture arrived. The backend sends an `emg`
 * message before the `fsm` update it causes, so the stored FSM state is the one the gesture met.
 */
export type EmgEntry = EmgMsg & { seq: number; at: number; moving: boolean };

export type DashboardState = Snapshot & {
  link: Link;
  /** Gesture keys currently held (keyboard emulator), for the key pad. */
  held: string[];
  /** Monotonic counter so the ribbon can key events uniquely. */
  emgSeq: number;
  emg: EmgEntry[];
};

const EMG_KEEP = 40;

let state: DashboardState = {
  vision: null,
  menu: null,
  fsm: null,
  system: null,
  session: null,
  emg_recent: [],
  emg: [],
  emgSeq: 0,
  link: "connecting",
  held: [],
};

const listeners = new Set<() => void>();

function set(next: Partial<DashboardState>) {
  state = { ...state, ...next };
  listeners.forEach((l) => l());
}

const ACTUATION = ["CLOSING", "HOLDING", "OPENING"];

function pushEmg(list: EmgEntry[], msg: EmgMsg, seq: number) {
  const moving = ACTUATION.includes(state.fsm?.state ?? "HOME");
  return [...list, { ...msg, seq, at: performance.now(), moving }].slice(-EMG_KEEP);
}

export function applyMessage(msg: ServerMessage) {
  switch (msg.type) {
    case "snapshot": {
      let seq = state.emgSeq;
      let emg: EmgEntry[] = [];
      for (const e of msg.data.emg_recent) emg = pushEmg(emg, e, ++seq);
      set({ ...msg.data, emg, emgSeq: seq });
      break;
    }
    case "emg":
      set({ emg: pushEmg(state.emg, msg.data, state.emgSeq + 1), emgSeq: state.emgSeq + 1 });
      break;
    case "vision":
      set({ vision: msg.data });
      break;
    case "menu":
      set({ menu: msg.data });
      break;
    case "fsm":
      set({ fsm: msg.data });
      break;
    case "system":
      set({ system: msg.data });
      break;
    case "session":
      set({ session: msg.data });
      break;
  }
}

export function setLink(link: Link) {
  if (state.link !== link) set({ link });
}

export function setHeld(held: string[]) {
  set({ held });
}

export function getState() {
  return state;
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function useDashboard<T>(select: (s: DashboardState) => T): T {
  return useSyncExternalStore(subscribe, () => select(state));
}
