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

/** A preference profile. `created_at` / `last_used`: Unix seconds, null when unknown or never used. */
export type UserInfo = {
  user: string;
  created_at: number | null;
  selections: number;
  accepted: number;
  last_used: number | null;
};

export type UsersMsg = { current: string; users: UserInfo[] };

/** A control the backend rejected; sent once, never part of the snapshot. */
export type NoticeMsg = { action: string | null; ok: false; message: string };

/** One confirmed selection with the menu it came from (GET /api/history, docs/interfaces.md section 9). */
export type HistorySelection = {
  id: string;
  time: number;
  object: string;
  region: string;
  grip: Grip;
  menu: "adaptive" | "full";
  rank: number | null;
  policy: MenuPolicy | null;
  items: Grip[];
  ranking_source: string | null;
  region_confidence: number | null;
  compatible: boolean;
  instructed: boolean;
  status: "pending" | "accepted" | "cancelled" | "failed";
  grasp_success: boolean | null;
};

export type HistoryMsg = {
  user: string;
  summary: { total: number; accepted: number; cancelled: number; adaptive: number; full: number; first_option: number };
  preferences: { object: string; region: string; grip: Grip; n: number }[];
  selections: HistorySelection[];
};

export type Snapshot = {
  vision: VisionMsg | null;
  menu: MenuMsg | null;
  fsm: FsmMsg | null;
  system: SystemMsg | null;
  session: SessionMsg | null;
  users?: UsersMsg | null;
  emg_recent: EmgMsg[];
};

export type ServerMessage =
  | { type: "snapshot"; data: Snapshot }
  | { type: "vision"; data: VisionMsg }
  | { type: "menu"; data: MenuMsg | null }
  | { type: "fsm"; data: FsmMsg }
  | { type: "emg"; data: EmgMsg }
  | { type: "system"; data: SystemMsg }
  | { type: "session"; data: SessionMsg }
  | { type: "users"; data: UsersMsg }
  | { type: "notice"; data: NoticeMsg };

export type GestureKey = "w" | "a" | "s" | "d" | "e";

export type ControlAction =
  | { action: "start_trial" }
  | { action: "end_trial"; grasp_success: boolean; notes: string }
  | { action: "set_session"; participant: string; condition: Condition }
  | { action: "add_user"; user: string };

export type ClientMessage =
  | { type: "key"; data: { key: GestureKey; down: boolean } }
  | { type: "control"; data: ControlAction };
