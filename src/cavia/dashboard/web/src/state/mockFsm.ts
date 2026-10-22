// TypeScript port of src/cavia/fsm/machine.py and src/cavia/emg/keyboard.py, used only in mock mode.
// The backend's Python FSM stays the source of truth (tests/fsm/vectors.json).

import type {
  Activity, EmgEvent, FsmMsg, FsmState, GestureKey, Grip, MenuKind, MenuMsg,
} from "../types/messages";

const ACTUATION: FsmState[] = ["CLOSING", "HOLDING", "OPENING"];
const MENUS: FsmState[] = ["ADAPTIVE", "FULL"];

export const FSM_SPEEDS = { close: 0.25, open: 0.35, heReturn: 0.5 };

export class MockFsm {
  state: FsmState = "HOME";
  menuId: number | null = null;
  adaptive: Grip[] = [];
  full: Grip[] = ["POWER", "PINCH", "TRIPOD", "LATERAL"];
  selected = 0;
  waitRelease = false;
  activeGrip: Grip | null = null;
  confirmedFrom: MenuKind | null = null;
  returning = false;
  returnTo: FsmState = "FULL";
  progress = 0;
  lastEvent: string | null = null;

  reset() {
    this.state = "HOME";
    this.menuId = null;
    this.adaptive = [];
    this.selected = 0;
    this.waitRelease = false;
    this.activeGrip = null;
    this.confirmedFrom = null;
    this.returning = false;
    this.returnTo = "FULL";
    this.lastEvent = null;
  }

  loadMenu(menu: MenuMsg): boolean {
    if (this.state !== "HOME") return false;
    this.menuId = menu.menu_id;
    this.full = [...menu.full_menu];
    this.adaptive = [...menu.items];
    this.selected = 0;
    this.waitRelease = false;
    this.lastEvent = "MENU_READY";
    this.state = menu.policy === "FULL_MENU" || this.adaptive.length === 0 ? "FULL" : "ADAPTIVE";
    return true;
  }

  items(): Grip[] {
    if (this.state === "ADAPTIVE") return this.adaptive;
    if (this.state === "FULL") return this.full;
    return [];
  }

  menuKind(): MenuKind | null {
    if (this.state === "ADAPTIVE") return "ADAPTIVE";
    if (this.state === "FULL") return "FULL";
    return this.confirmedFrom;
  }

  onEvent(event: EmgEvent) {
    this.lastEvent = event;
    if (MENUS.includes(this.state)) {
      const items = this.items();
      if (event === "SF") this.selected = (this.selected + 1) % items.length;
      else if (event === "SE") this.selected = (this.selected - 1 + items.length) % items.length;
      else if (event === "LF") {
        this.activeGrip = items[this.selected];
        this.confirmedFrom = this.menuKind();
        this.state = "HOLDING";
        this.waitRelease = false;
      } else if (event === "LE" && this.state === "ADAPTIVE") {
        this.state = "FULL";
        this.selected = 0;
      } else if (event === "HE") {
        this.reset();
        this.lastEvent = "HE";
      }
      return;
    }
    if (ACTUATION.includes(this.state) && event === "HE" && !this.returning) this.startReturn("FULL");
  }

  onActivity(activity: Activity) {
    if (!ACTUATION.includes(this.state) || this.returning) return;
    this.lastEvent = activity;
    if (activity === "REST") {
      this.state = "HOLDING";
      this.waitRelease = false;
    } else if (activity === "INVALID") {
      this.state = "HOLDING";
      this.waitRelease = true;
    } else if (this.waitRelease) {
      return;
    } else if (activity === "FLEX_ACTIVE") {
      this.state = "CLOSING";
    } else if (activity === "EXT_ACTIVE") {
      this.state = "OPENING";
    }
  }

  abort() {
    if (ACTUATION.includes(this.state)) this.startReturn("HOME");
    else this.reset();
    this.lastEvent = "ABORT";
  }

  private startReturn(destination: FsmState) {
    this.state = "OPENING";
    this.returning = true;
    this.returnTo = destination;
    this.waitRelease = false;
  }

  tick(dt: number) {
    dt = Math.max(0, dt);
    if (this.state === "CLOSING") {
      this.progress = Math.min(1, this.progress + FSM_SPEEDS.close * dt);
    } else if (this.state === "OPENING") {
      const speed = this.returning ? FSM_SPEEDS.heReturn : FSM_SPEEDS.open;
      this.progress = Math.max(0, this.progress - speed * dt);
      if (this.returning && this.progress <= 0) {
        if (this.returnTo === "HOME") {
          this.reset();
          return;
        }
        this.state = "FULL";
        this.selected = 0;
        this.returning = false;
        this.waitRelease = false;
        this.activeGrip = null;
        this.confirmedFrom = null;
      }
    }
  }

  status(ts: number): FsmMsg {
    const items = this.items();
    return {
      ts,
      menu_id: this.menuId,
      state: this.state,
      menu_kind: this.menuKind(),
      selected_index: this.selected,
      selected_grip: items.length ? items[this.selected] : this.activeGrip,
      active_grip: this.activeGrip,
      grip_progress: this.progress,
      wait_release: this.waitRelease,
      returning: this.returning,
      last_event: this.lastEvent,
    };
  }
}

const GESTURES: Record<GestureKey, EmgEvent> = { w: "SE", s: "SF", a: "LF", d: "LE", e: "HE" };

/** Mirrors KeyboardEmg: one press = one gesture, a press while another key is held is INVALID. */
export class KeyboardEmg {
  held = new Set<GestureKey>();

  press(key: GestureKey): EmgEvent | null {
    if (this.held.has(key)) return null;
    const ambiguous = this.held.size > 0;
    this.held.add(key);
    return ambiguous ? "INVALID" : GESTURES[key];
  }

  release(key: GestureKey) {
    this.held.delete(key);
  }

  releaseAll() {
    this.held.clear();
  }

  activity(): Activity {
    const flex = this.held.has("a");
    const ext = this.held.has("d");
    if (flex && ext) return "INVALID";
    if (flex) return "FLEX_ACTIVE";
    if (ext) return "EXT_ACTIVE";
    return "REST";
  }
}
