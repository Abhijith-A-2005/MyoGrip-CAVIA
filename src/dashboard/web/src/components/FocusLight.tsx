import { useLayoutEffect, useRef, useState } from "react";
import type { FocusArea } from "../labels";
import "./FocusLight.css";

type Rect = { x: number; y: number; w: number; h: number };

/** Rect of a panel in stage coordinates (undoing the stage's fit-to-window scale). */
function measure(area: FocusArea): Rect | null {
  const stage = document.querySelector<HTMLElement>(".stage");
  const el = document.querySelector<HTMLElement>(`[data-area="${area}"]`);
  if (!stage || !el) return null;
  const s = stage.getBoundingClientRect();
  const r = el.getBoundingClientRect();
  const k = s.width / stage.offsetWidth || 1;
  return { x: (r.left - s.left) / k, y: (r.top - s.top) / k, w: r.width / k, h: r.height / k };
}

/** Height of the glow that spills above the focused panel's top edge. */
const HALO = 90;

/**
 * The page's one light source. It pools on the focused panel's top edge, spilling a halo above
 * and falling into the panel, like the light at the top of the reference poster. When focus
 * moves, the light glides there. It tracks the panel while the menu
 * widths animate, so it always lands on the final position.
 */
export function FocusLight({ area }: { area: FocusArea }) {
  const [rect, setRect] = useState<Rect | null>(null);
  const raf = useRef(0);

  useLayoutEffect(() => {
    const el = document.querySelector<HTMLElement>(`[data-area="${area}"]`);
    if (!el) return;
    const update = () => setRect(measure(area));
    update();
    // Follow the panel through its own width/flex transition.
    const until = performance.now() + 700;
    const follow = () => {
      update();
      if (performance.now() < until) raf.current = requestAnimationFrame(follow);
    };
    raf.current = requestAnimationFrame(follow);
    const ro = new ResizeObserver(update);
    ro.observe(el);
    window.addEventListener("resize", update);
    return () => {
      cancelAnimationFrame(raf.current);
      ro.disconnect();
      window.removeEventListener("resize", update);
    };
  }, [area]);

  if (!rect) return null;
  return (
    <div className="focus-light" aria-hidden>
      <div
        className="focus-halo"
        style={{ left: rect.x, width: rect.w, top: rect.y - HALO, height: HALO * 2 }}
      />
      <div className="focus-fall" style={{ left: rect.x, width: rect.w, top: rect.y, height: rect.h }} />
    </div>
  );
}
