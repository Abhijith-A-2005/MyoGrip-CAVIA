// Mock backend: scripted vision + menus, real FSM port, keyboard-driven. Emits the same ServerMessages as /ws.
// URL options: ?policy=TOP_TWO|ONE_CONFIRM|FULL_COMPATIBLE|FULL_MENU  &camera=lost  &participant=P01
//              &script=<t>:<key>[:<hold>],...  presses keys automatically (e.g. 3:s,3.5:a:1.5)

import type {
  Activity, Box, ClientMessage, Condition, GestureKey, Grip, MenuMsg, MenuPolicy, ServerMessage, SessionMsg, SystemMsg,
  UserInfo, UsersMsg, VisionMsg,
} from "../types/messages";
import { KeyboardEmg, MockFsm } from "./mockFsm";
import type { Transport } from "./ws";
import { applyMessage, setHeld, setLink } from "./store";

const TICK_MS = 33;
const SEARCH_S = 2.4;
const REARM_S = 1.6;
const FULL_MENU: Grip[] = ["POWER", "PINCH", "TRIPOD", "LATERAL"];

type Scenario = Pick<MenuMsg, "policy" | "items" | "scores" | "confidence" | "condition"> & {
  object: string;
  region: string;
  view: typeof HANDLE_VIEW;
};

// Boxes match public/mock-frame-*.svg; the wrist points the reticle (frame centre) at the region.
const HANDLE_VIEW = { cup: [0.15, 0.2, 0.55, 0.84] as Box, region: [0.45, 0.34, 0.55, 0.68] as Box, frame: "/mock-frame-handle.svg" };
const BODY_VIEW = { cup: [0.35, 0.2, 0.75, 0.84] as Box, region: [0.35, 0.2, 0.65, 0.84] as Box, frame: "/mock-frame-body.svg" };

const SCENARIOS: Record<MenuPolicy, Scenario> = {
  TOP_TWO: {
    policy: "TOP_TWO", condition: "C3_ADAPTIVE", object: "cup", region: "handle",
    items: ["LATERAL", "PINCH"], scores: [0.71, 0.29],
    confidence: { vision: 0.87, evidence_n: 6, top_share: 0.71, margin: 0.42 },
    view: HANDLE_VIEW,
  },
  ONE_CONFIRM: {
    policy: "ONE_CONFIRM", condition: "C3_ADAPTIVE", object: "cup", region: "handle",
    items: ["LATERAL"], scores: [0.86],
    confidence: { vision: 0.91, evidence_n: 9, top_share: 0.86, margin: 0.72 },
    view: HANDLE_VIEW,
  },
  FULL_COMPATIBLE: {
    policy: "FULL_COMPATIBLE", condition: "C2_STATIC", object: "cup", region: "body",
    items: ["POWER", "LATERAL"], scores: [0.5, 0.5],
    confidence: { vision: 0.74, evidence_n: 1, top_share: 0.5, margin: 0 },
    view: BODY_VIEW,
  },
  FULL_MENU: {
    policy: "FULL_MENU", condition: "C1_MANUAL", object: "cup", region: "handle",
    items: [], scores: [],
    confidence: { vision: 0.87, evidence_n: 0, top_share: 0, margin: 0 },
    view: HANDLE_VIEW,
  },
};

/** Which scenario a condition shows; Adaptive keeps the current adaptive policy (e.g. ONE_CONFIRM). */
const SCENARIO_FOR: Record<Condition, (current: Scenario) => Scenario> = {
  C1_MANUAL: () => SCENARIOS.FULL_MENU,
  C2_STATIC: () => SCENARIOS.FULL_COMPATIBLE,
  C3_ADAPTIVE: (current) => (current.condition === "C3_ADAPTIVE" ? current : SCENARIOS.TOP_TWO),
};

const GESTURE_KEYS = new Set(["w", "a", "s", "d", "e"]);
/** Same rule as cavia.server.session.participant_id. */
const PARTICIPANT_ID = /^[A-Z0-9][A-Z0-9_-]{0,23}$/;

/** Two profiles with some history, as left behind by `python -m cavia --user 1` / `--user 2`. */
function mockUsers(): UserInfo[] {
  const day = 86400;
  const t = Date.now() / 1000;
  return [
    { user: "1", created_at: t - 3 * day, selections: 14, accepted: 12, last_used: t - 2 * 3600 },
    { user: "2", created_at: t - 2 * day, selections: 6, accepted: 5, last_used: t - day },
  ];
}
const ACTUATION = ["CLOSING", "HOLDING", "OPENING"];

/** Still image standing in for the camera feed in mock mode. */
export function mockFrameUrl(params: URLSearchParams): string {
  const policy = (params.get("policy")?.toUpperCase() ?? "TOP_TWO") as MenuPolicy;
  return (SCENARIOS[policy] ?? SCENARIOS.TOP_TWO).view.frame;
}

export function startMock(params: URLSearchParams): Transport {
  const policy = (params.get("policy")?.toUpperCase() ?? "TOP_TWO") as MenuPolicy;
  // The drawer can switch condition at runtime; the next menu then uses that condition's scenario.
  let scenario = SCENARIOS[policy] ?? SCENARIOS.TOP_TWO;
  const cameraLost = params.get("camera") === "lost";
  let participant = params.get("participant") ?? "P01";
  let trialActive = false;
  const userList = mockUsers();

  const fsm = new MockFsm();
  const keys = new KeyboardEmg();
  const t0 = performance.now();
  const now = () => (performance.now() - t0) / 1000;
  const emit = (msg: ServerMessage) => applyMessage(msg);

  let menuId = 0;
  let trial = 0;
  let searchStart = 0;
  let lastTick = now();
  let lastSystem = -1;
  let lastActivity: Activity = "REST";
  let frameSeq = 0;
  let lastFsmKey = "";

  const session = (): SessionMsg => ({ participant, condition: scenario.condition, trial, trial_active: trialActive });

  const users = (): UsersMsg => ({ current: participant, users: userList.map((u) => ({ ...u })) });

  const reject = (action: string, message: string) => emit({ type: "notice", data: { action, ok: false, message } });

  const register = (user: string) => {
    if (!userList.some((u) => u.user === user)) {
      userList.push({ user, created_at: Date.now() / 1000, selections: 0, accepted: 0, last_used: null });
    }
  };
  register(participant);

  const system = (t: number): SystemMsg => ({
    camera: cameraLost
      ? { status: "stale", source: "XIAO", fps: 0, latency_ms: 0 }
      : { status: "live", source: "XIAO", fps: 17.4 + Math.sin(t * 0.7) * 0.9, latency_ms: 132 + Math.round(Math.sin(t * 1.3) * 14) },
    vision: { status: cameraLost ? "degraded" : "ok", model: "yolo26n" },
    hand_link: { status: "connected", battery_pct: 82 },
    emg_source: "keyboard",
  });

  const jitter = (b: Box, t: number, amp: number): Box => {
    const dx = Math.sin(t * 2.1) * amp;
    const dy = Math.cos(t * 1.7) * amp;
    return [b[0] + dx, b[1] + dy, b[2] + dx, b[3] + dy];
  };

  const vision = (t: number): VisionMsg => {
    frameSeq += 1;
    const base = { ts: t, frame_seq: frameSeq, source: "XIAO" as const };
    if (cameraLost) {
      return { ...base, state: "NO_OBJECT", object: null, region: null, region_confidence: 0,
        det_conf: 0, reticle_score: 0, stability: 0, stable: false, box: null, region_box: null };
    }
    const held = fsm.state !== "HOME";
    const k = held ? 1 : Math.min(1, Math.max(0, (t - searchStart) / SEARCH_S));
    const conf = held ? scenario.confidence.vision : 0.38 + k * (scenario.confidence.vision - 0.38);
    const locked = held || k >= 1;
    const amp = held ? 0.003 : 0.014 * (1 - k) + 0.003;
    return {
      ...base,
      state: locked ? "LOCKED" : "SEARCHING",
      object: scenario.object,
      region: scenario.region,
      region_confidence: conf,
      det_conf: Math.min(0.97, conf + 0.06),
      reticle_score: Math.min(1, 0.3 + k * 0.38),
      stability: Math.min(1, 0.25 + k * 0.65),
      stable: locked,
      box: jitter(scenario.view.cup, t, amp),
      region_box: jitter(scenario.view.region, t, amp),
    };
  };

  const buildMenu = (t: number): MenuMsg => ({
    ts: t,
    menu_id: ++menuId,
    condition: scenario.condition,
    context: { object: scenario.object, region: scenario.region, region_confidence: scenario.confidence.vision },
    policy: scenario.policy,
    items: [...scenario.items],
    scores: [...scenario.scores],
    confidence: { ...scenario.confidence },
    full_menu: FULL_MENU,
  });

  const publishFsm = (t: number, force = false) => {
    const s = fsm.status(t);
    const key = `${s.state}|${s.selected_index}|${s.active_grip}|${s.grip_progress.toFixed(3)}|${s.wait_release}|${s.returning}`;
    if (force || key !== lastFsmKey) {
      lastFsmKey = key;
      emit({ type: "fsm", data: s });
    }
  };

  let wasHome = true;

  const step = () => {
    const t = now();
    const dt = Math.min(0.1, t - lastTick);
    lastTick = t;

    const activity = keys.activity();
    fsm.onActivity(activity);
    // Activity only matters in actuation; leaving it always closes the last span with a rest.
    const reported: Activity = ACTUATION.includes(fsm.state) ? activity : "REST";
    if (reported !== lastActivity) {
      emit({ type: "emg", data: { ts: t, source: "keyboard", activity: reported } });
      lastActivity = reported;
    }
    fsm.tick(dt);

    const v = vision(t);
    emit({ type: "vision", data: v });

    if (fsm.state === "HOME") {
      if (!wasHome) {
        // Back at CAVIA Home: clear the menus and search again shortly.
        emit({ type: "menu", data: null });
        searchStart = t + REARM_S;
      } else if (v.state === "LOCKED" && t >= searchStart) {
        const menu = buildMenu(t);
        fsm.loadMenu(menu);
        emit({ type: "menu", data: menu });
        emit({ type: "session", data: session() });
      }
    }
    wasHome = fsm.state === "HOME";

    publishFsm(t);
    if (Math.floor(t) !== lastSystem) {
      lastSystem = Math.floor(t);
      emit({ type: "system", data: system(t) });
    }
  };

  setLink("mock");
  emit({
    type: "snapshot",
    data: {
      vision: vision(0), menu: null, fsm: fsm.status(0), system: system(0), session: session(), users: users(),
      emg_recent: [],
    },
  });
  const timer = window.setInterval(step, TICK_MS);
  const scripted = scheduleScript(params.get("script"), (key, down) => transport.send({ type: "key", data: { key, down } }));

  const transport: Transport = {
    send: (msg: ClientMessage) => {
      if (msg.type === "key") {
        const { key, down } = msg.data;
        if (!GESTURE_KEYS.has(key)) return;
        if (down) {
          const event = keys.press(key);
          if (event) {
            fsm.onEvent(event);
            emit({ type: "emg", data: { ts: now(), source: "keyboard", event } });
          }
        } else {
          keys.release(key);
        }
        setHeld([...keys.held]);
        publishFsm(now());
      } else {
        const c = msg.data;
        if (c.action === "start_trial") {
          trial += 1;
          trialActive = true;
        } else if (c.action === "end_trial") {
          trialActive = false;
        } else if (c.action === "add_user") {
          const user = c.user.trim().toUpperCase();
          if (!PARTICIPANT_ID.test(user)) return reject(c.action, "Use letters, digits, - or _ (up to 24 characters) for the participant ID");
          if (users().users.some((u) => u.user === user)) return reject(c.action, `User ${user} already exists`);
          register(user);
          emit({ type: "users", data: users() });
          return;
        } else {
          const next = c.participant.trim().toUpperCase();
          if (trialActive) return reject(c.action, "End the current trial before changing the session");
          if (!PARTICIPANT_ID.test(next)) return reject(c.action, "Use letters, digits, - or _ (up to 24 characters) for the participant ID");
          if (next !== participant) {
            if (ACTUATION.includes(fsm.state) || keys.held.size > 0) {
              return reject(c.action, "Change the session before confirming a grip, with all keys released");
            }
            fsm.reset(); // an unconfirmed menu is cleared; the next lock ranks for the new user
          }
          participant = next;
          register(participant);
          scenario = SCENARIO_FOR[c.condition](scenario);
          emit({ type: "users", data: users() });
        }
        emit({ type: "session", data: session() });
      }
    },
    close: () => {
      window.clearInterval(timer);
      scripted.forEach((id) => window.clearTimeout(id));
    },
  };
  return transport;
}

/** Parses `t:key[:hold]` steps; a missing hold is a 0.12 s tap. Returns timer ids for cleanup. */
function scheduleScript(script: string | null, press: (key: GestureKey, down: boolean) => void): number[] {
  if (!script) return [];
  const ids: number[] = [];
  for (const step of script.split(",")) {
    const [at, key, hold] = step.split(":");
    if (!GESTURE_KEYS.has(key)) continue;
    const start = Number(at) * 1000;
    const end = start + (hold ? Number(hold) : 0.12) * 1000;
    if (!Number.isFinite(start) || !Number.isFinite(end)) continue;
    ids.push(window.setTimeout(() => press(key as GestureKey, true), start));
    ids.push(window.setTimeout(() => press(key as GestureKey, false), end));
  }
  return ids;
}

