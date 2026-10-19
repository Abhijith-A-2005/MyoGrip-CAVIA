// Display names. The object set is still being finalised (decision Q2), so keep every mapping here.

import type { Condition, FsmMsg, FsmState, Grip, MenuPolicy } from "./types/messages";

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
  LATERAL: "Thumb against the side of the index",
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
