import { readFileSync } from "node:fs";
import { MockFsm, FSM_SPEEDS } from "../src/state/mockFsm.ts";
// Shared FSM spec (also run by pytest against the Python FSM).
const V = JSON.parse(readFileSync(new URL("../../../../../tests/fsm/vectors.json", import.meta.url), "utf8"));
FSM_SPEEDS.close = V.config.close_speed; FSM_SPEEDS.open = V.config.open_speed; FSM_SPEEDS.heReturn = V.config.he_return_speed;
let fails = 0, steps = 0;
for (const seq of V.sequences) {
  const f = new MockFsm(); f.full = V.full_menu;
  seq.steps.forEach((st: any, i: number) => {
    steps++;
    if (st.op === "menu") f.loadMenu({ menu_id: 1, policy: st.policy ?? "TOP_TWO", items: st.items, full_menu: V.full_menu } as any);
    else if (st.op === "event") f.onEvent(st.value);
    else if (st.op === "activity") f.onActivity(st.value);
    else if (st.op === "tick") f.tick(st.dt);
    else if (st.op === "abort") f.abort();
    const e = st.expect, bad: string[] = [];
    if ("state" in e && f.state !== e.state) bad.push(`state ${f.state}!=${e.state}`);
    if ("index" in e && f.selected !== e.index) bad.push(`index ${f.selected}!=${e.index}`);
    if ("gate" in e && f.waitRelease !== e.gate) bad.push(`gate`);
    if ("progress" in e && Math.abs(f.progress - e.progress) > 1e-9) bad.push(`progress ${f.progress}!=${e.progress}`);
    if ("grip" in e && f.activeGrip !== e.grip) bad.push(`grip ${f.activeGrip}!=${e.grip}`);
    if (bad.length) { fails++; console.log(`FAIL ${seq.name} step ${i + 1}: ${bad.join(", ")}`); }
  });
}
console.log(`${V.sequences.length} sequences, ${steps} steps, ${fails} failures`);
process.exit(fails ? 1 : 0);
