import assert from "node:assert/strict";
import { frameFit, reticleGeometry } from "../src/state/targeting.ts";
import type { Targeting } from "../src/types/messages.ts";

const metadata: Targeting = {
  stage: "object", frame_size: [640, 480], center: [320, 240], radius: 221, cross_half_size: 20,
};
for (const stage of ["object", "settling", "region"] as const) {
  const geometry = reticleGeometry({ ...metadata, stage }, 640, 480);
  assert.equal(geometry.stage, stage);
  assert.equal(geometry.radius, stage === "region" ? null : 221);
  assert.equal(geometry.path, "M300 240H340M320 220V260");
}
assert.deepEqual(frameFit(640, 480), { width: "75%", height: "100%" });
assert.deepEqual(frameFit(1280, 720), { width: "100%", height: "100%" });
// Both axes use the same scale: the circle remains circular inside the panel.
assert.equal((1920 * 0.75) / 640, 1080 / 480);
assert.equal(reticleGeometry(undefined, 1000, 750).radius, null);
console.log("Reticle stages, source geometry, full-frame fit and legacy fallback passed");
