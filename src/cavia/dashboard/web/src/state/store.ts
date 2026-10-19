import { useSyncExternalStore } from "react";
import type { EmgMsg, ServerMessage, Snapshot } from "../types/messages";

export type Link = "connecting" | "open" | "reconnecting" | "mock";

export type DashboardState = Snapshot & {
  link: Link;
  /** Gesture keys currently held (keyboard emulator), for the key pad. */
  held: string[];
  /** Monotonic counter so the ribbon can key events uniquely. */
  emgSeq: number;
  emg: (EmgMsg & { seq: number })[];
};

const EMG_KEEP = 24;

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

function pushEmg(list: DashboardState["emg"], msg: EmgMsg, seq: number) {
  return [...list, { ...msg, seq }].slice(-EMG_KEEP);
}

export function applyMessage(msg: ServerMessage) {
  switch (msg.type) {
    case "snapshot": {
      let seq = state.emgSeq;
      let emg: DashboardState["emg"] = [];
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
