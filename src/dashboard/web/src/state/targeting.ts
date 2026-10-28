import type { Targeting } from "../types/messages";

/** Fit the complete source frame inside the dashboard's 16:9 camera panel. */
export function frameFit(width: number, height: number) {
  const aspect = width / height;
  return {
    width: `${Math.min(1, aspect / (16 / 9)) * 100}%`,
    height: `${Math.min(1, (16 / 9) / aspect) * 100}%`,
  };
}

export function reticleGeometry(targeting: Targeting | null | undefined, width: number, height: number) {
  const [cx, cy] = targeting?.center ?? [width / 2, height / 2];
  const size = targeting?.cross_half_size ?? width * (20 / 640);
  return {
    cx, cy,
    stage: targeting?.stage ?? "region",
    radius: targeting && targeting.stage !== "region" ? targeting.radius : null,
    path: `M${cx - size} ${cy}H${cx + size}M${cx} ${cy - size}V${cy + size}`,
  };
}
