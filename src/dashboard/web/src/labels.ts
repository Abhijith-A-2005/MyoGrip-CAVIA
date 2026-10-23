// Display names. The object set is still being finalised (decision Q2), so keep every mapping here.

import type { Condition, FsmMsg, FsmState, Grip, MenuMsg, MenuPolicy } from "./types/messages";

export const OBJECT_LABEL: Record<string, string> = {
  cup: "Mug",
  bottle: "Bottle",
  toothbrush: "Pen",
  spoon: "Spoon",
  "cell phone": "Phone",
  remote: "Remote",
  book: "Small box",
};

/** Objects detected through a COCO stand-in class, flagged so nobody reads "toothbrush" as a mistake. */
export const STAND_IN: Record<string, string> = { toothbrush: "detected as toothbrush", book: "detected as book" };

export const REGION_LABEL: Record<string, string> = {
  body: "Body",
  handle: "Handle",
  cap: "Cap",
  shank: "Tip end",
  side_edge: "Side edge",
  lower_support: "Lower edge",
  cover_face: "Face",
};

export const GRIP_LABEL: Record<Grip, string> = {
  POWER: "Power",
  PINCH: "Pinch",
  TRIPOD: "Tripod",
  LATERAL: "Lateral",
};

export const GRIP_HINT: Record<Grip, string> = {
  POWER: "Whole hand around a cylinder",
  PINCH: "Thumb and index tips",
  TRIPOD: "Thumb with two fingers",
  LATERAL: "Thumb on the side of the index",
};

export const CONDITION_LABEL: Record<Condition, string> = {
  C1_MANUAL: "Manual cycling",
  C2_STATIC: "Static CAVIA",
  C3_ADAPTIVE: "Adaptive CAVIA",
};

export const POLICY_SUBTITLE: Record<MenuPolicy, string> = {
  ONE_CONFIRM: "One clear choice. Hold a long flex to confirm",
  TOP_TWO: "Two likely grips",
  FULL_COMPATIBLE: "Every grip that fits this region",
  FULL_MENU: "Manual mode. Full menu only",
};

export const STATE_LABEL: Record<FsmState, string> = {
  HOME: "Home",
  ADAPTIVE: "Adaptive",
  FULL: "Full menu",
  CLOSING: "Closing",
  HOLDING: "Holding",
  OPENING: "Opening",
};

export type FocusArea = "camera" | "adaptive" | "full" | "hand";

/** Brief section 6.3: the focused panel is a pure function of the FSM state. */
export function focusArea(fsm: FsmMsg | null): FocusArea {
  switch (fsm?.state) {
    case "ADAPTIVE":
      return "adaptive";
    case "FULL":
      return "full";
    case "CLOSING":
    case "HOLDING":
    case "OPENING":
      return "hand";
    default:
      return "camera";
  }
}

export const objectLabel = (o: string | null) => (o ? OBJECT_LABEL[o] ?? o : "Nothing yet");
export const regionLabel = (r: string | null) => (r ? REGION_LABEL[r] ?? r : "");

/** Moves to reach item i from the top in a wrapping menu of n items. */
export const movesToReach = (i: number, n: number) => Math.min(i, n - i);
export const movesText = (m: number) => (m === 0 ? "Ready" : m === 1 ? "1 move" : `${m} moves`);

/** One-line explanation of why the Adaptive Menu has this size. */
export function menuReason(menu: MenuMsg): string {
  const v = Math.round(menu.confidence.vision * 100);
  if (menu.condition === "C2_STATIC") return `Region ${v}% sure. Fixed order, no preference history.`;
  const n = menu.confidence.evidence_n;
  const top = Math.round(menu.confidence.top_share * 100);
  return `Region ${v}% sure. ${n} past choice${n === 1 ? "" : "s"} here. Top grip ${top}%.`;
}

/** Relative time for a Unix timestamp in seconds: "5 min ago", "yesterday". */
export function ago(unix: number | null): string {
  if (unix == null) return "";
  const s = Math.max(0, Date.now() / 1000 - unix);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  const d = Math.floor(s / 86400);
  return d === 1 ? "yesterday" : `${d} days ago`;
}
