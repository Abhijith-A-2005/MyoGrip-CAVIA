// Message shapes shared with the Python backend. Source of truth: docs/interfaces.md + DASHBOARD_BRIEF.md section 11.

export type Grip = "POWER" | "PINCH" | "TRIPOD" | "LATERAL";
export type VisionState = "NO_OBJECT" | "SEARCHING" | "LOCKED" | "LOST";
export type FsmState = "HOME" | "ADAPTIVE" | "FULL" | "CLOSING" | "HOLDING" | "OPENING";
export type MenuKind = "ADAPTIVE" | "FULL";
export type MenuPolicy = "FULL_COMPATIBLE" | "TOP_TWO" | "ONE_CONFIRM" | "FULL_MENU";
export type Condition = "C1_MANUAL" | "C2_STATIC" | "C3_ADAPTIVE";
export type EmgEvent = "SF" | "SE" | "LF" | "LE" | "HE" | "REST" | "INVALID";
export type Activity = "REST" | "FLEX_ACTIVE" | "EXT_ACTIVE" | "INVALID";
export type HealthStatus =
  | "live" | "ok" | "connected"
  | "degraded"
  | "stale" | "down" | "disconnected";

/** [x1, y1, x2, y2], normalised 0..1 in frame coordinates. */
export type Box = [number, number, number, number];

export type VisionMsg = {
  ts: number;
  frame_seq: number;
  state: VisionState;
  object: string | null;
  region: string | null;
  region_confidence: number;
  det_conf: number;
  reticle_score: number;
  stability: number;
  stable: boolean;
  source?: "XIAO" | "LAPTOP";
  box?: Box | null;
  region_box?: Box | null;
};

export type MenuMsg = {
  ts: number;
  menu_id: number;
  condition: Condition;
  context: { object: string | null; region: string | null; region_confidence: number };
  policy: MenuPolicy;
  items: Grip[];
  scores: number[];
  confidence: { vision: number; evidence_n: number; top_share: number; margin: number };
  full_menu: Grip[];
};

export type FsmMsg = {
  ts: number;
  menu_id: number | null;
  state: FsmState;
  menu_kind: MenuKind | null;
  selected_index: number;
  selected_grip: Grip | null;
  active_grip: Grip | null;
  grip_progress: number;
  wait_release: boolean;
  returning?: boolean;
  last_event: string | null;
};

export type EmgMsg = {
  ts: number;
  source: "device" | "keyboard" | "replay";
  event?: EmgEvent;
  activity?: Activity;
};

export type SystemMsg = {
  /** latency_ms 0 = not measured (hidden in the UI). */
  camera: { status: HealthStatus; source: "XIAO" | "LAPTOP"; fps: number; latency_ms: number };
  vision: { status: HealthStatus; model: string };
  hand_link: { status: HealthStatus; battery_pct: number | null };
  emg_source: "device" | "keyboard" | "replay";
};

export type SessionMsg = {
  participant: string;
  condition: Condition;
  trial: number;
  trial_active: boolean;
};

export type Snapshot = {
  vision: VisionMsg | null;
  menu: MenuMsg | null;
  fsm: FsmMsg | null;
  system: SystemMsg | null;
  session: SessionMsg | null;
  emg_recent: EmgMsg[];
};

export type ServerMessage =
  | { type: "snapshot"; data: Snapshot }
  | { type: "vision"; data: VisionMsg }
  | { type: "menu"; data: MenuMsg | null }
  | { type: "fsm"; data: FsmMsg }
  | { type: "emg"; data: EmgMsg }
  | { type: "system"; data: SystemMsg }
  | { type: "session"; data: SessionMsg };

export type GestureKey = "w" | "a" | "s" | "d" | "e";

export type ControlAction =
  | { action: "start_trial" }
  | { action: "end_trial"; grasp_success: boolean; notes: string }
  | { action: "set_session"; participant: string; condition: Condition };

export type ClientMessage =
  | { type: "key"; data: { key: GestureKey; down: boolean } }
  | { type: "control"; data: ControlAction };
