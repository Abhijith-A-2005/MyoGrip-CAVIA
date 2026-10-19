// Mock backend: scripted vision + menus, real FSM port, keyboard-driven. Emits the same ServerMessages as /ws.
// URL options: ?policy=TOP_TWO|ONE_CONFIRM|FULL_COMPATIBLE|FULL_MENU  &camera=lost  &participant=P01
//              &script=<t>:<key>[:<hold>],...  presses keys automatically (e.g. 3:s,3.5:a:1.5)

import type {
  Activity, Box, ClientMessage, GestureKey, Grip, MenuMsg, MenuPolicy, ServerMessage, SessionMsg, SystemMsg,
  VisionMsg,
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
  box: Box;
  regionBox: Box;
};

const CUP_BOX: Box = [0.3, 0.2, 0.7, 0.84];
const HANDLE_BOX: Box = [0.6, 0.34, 0.7, 0.68];
const BODY_BOX: Box = [0.3, 0.2, 0.6, 0.84];

const SCENARIOS: Record<MenuPolicy, Scenario> = {
  TOP_TWO: {
    policy: "TOP_TWO", condition: "C3_ADAPTIVE", object: "cup", region: "handle",
    items: ["LATERAL", "PINCH"], scores: [0.71, 0.29],
    confidence: { vision: 0.87, evidence_n: 6, top_share: 0.71, margin: 0.42 },
    box: CUP_BOX, regionBox: HANDLE_BOX,
  },
  ONE_CONFIRM: {
    policy: "ONE_CONFIRM", condition: "C3_ADAPTIVE", object: "cup", region: "handle",
    items: ["LATERAL"], scores: [0.86],
    confidence: { vision: 0.91, evidence_n: 9, top_share: 0.86, margin: 0.72 },
    box: CUP_BOX, regionBox: HANDLE_BOX,
  },
  FULL_COMPATIBLE: {
    policy: "FULL_COMPATIBLE", condition: "C2_STATIC", object: "cup", region: "body",
    items: ["POWER", "LATERAL"], scores: [0.5, 0.5],
    confidence: { vision: 0.74, evidence_n: 1, top_share: 0.5, margin: 0 },
    box: CUP_BOX, regionBox: BODY_BOX,
  },
  FULL_MENU: {
    policy: "FULL_MENU", condition: "C1_MANUAL", object: "cup", region: "handle",
    items: [], scores: [],
    confidence: { vision: 0.87, evidence_n: 0, top_share: 0, margin: 0 },
    box: CUP_BOX, regionBox: HANDLE_BOX,
  },
};

const GESTURE_KEYS = new Set(["w", "a", "s", "d", "e"]);
const ACTUATION = ["CLOSING", "HOLDING", "OPENING"];

export function startMock(params: URLSearchParams): Transport {
  const policy = (params.get("policy")?.toUpperCase() ?? "TOP_TWO") as MenuPolicy;
  const scenario = SCENARIOS[policy] ?? SCENARIOS.TOP_TWO;
  const cameraLost = params.get("camera") === "lost";
  const participant = params.get("participant") ?? "P01";

  const fsm = new MockFsm();
  const keys = new KeyboardEmg();
  const t0 = performance.now();
  const now = () => (performance.now() - t0) / 1000;
  const emit = (msg: ServerMessage) => applyMessage(msg);

  let menuId = 0;
  let trial = 11;
  let searchStart = 0;
  let lastTick = now();
  let lastSystem = -1;
  let lastActivity: Activity = "REST";
  let frameSeq = 0;
  let lastFsmKey = "";

  const session = (): SessionMsg => ({
    participant, condition: scenario.condition, trial, trial_active: fsm.state !== "HOME",
  });

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
      box: jitter(scenario.box, t, amp),
      region_box: jitter(scenario.regionBox, t, amp),
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
    if (activity !== lastActivity && ACTUATION.includes(fsm.state)) {
      emit({ type: "emg", data: { ts: t, source: "keyboard", activity } });
    }
    lastActivity = activity;
    fsm.tick(dt);

    const v = vision(t);
    emit({ type: "vision", data: v });

    if (fsm.state === "HOME") {
      if (!wasHome) {
        // Back at CAVIA Home: clear the menus and search again shortly.
        emit({ type: "menu", data: null });
        searchStart = t + REARM_S;
      } else if (v.state === "LOCKED" && t >= searchStart) {
        trial += 1;
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
    data: { vision: vision(0), menu: null, fsm: fsm.status(0), system: system(0), session: session(), emg_recent: [] },
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
      } else if (msg.data.action === "set_session") {
        // Mock keeps the scripted scenario; only the participant label follows the drawer.
        emit({ type: "session", data: { ...session(), participant: msg.data.participant } });
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

