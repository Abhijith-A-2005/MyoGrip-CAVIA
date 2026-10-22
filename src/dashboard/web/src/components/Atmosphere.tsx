import { useEffect, useRef } from "react";
import "./Atmosphere.css";

const COUNT = 28;

type Speck = { x: number; y: number; r: number; vy: number; phase: number; base: number };

function spawn(w: number, h: number, anywhere: boolean): Speck {
  // Most specks live in the upper half, near the light, as in the reference poster.
  const y = anywhere ? Math.pow(Math.random(), 1.6) * h : h + 10;
  return {
    x: Math.random() * w,
    y,
    r: 0.6 + Math.random() * 1.4,
    vy: 4 + Math.random() * 9,
    phase: Math.random() * Math.PI * 2,
    base: 0.06 + Math.random() * 0.16,
  };
}

/** Background specks drifting up through the light, plus film grain. Off with reduced motion. */
export function Atmosphere() {
  const canvas = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const el = canvas.current;
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (!el || reduced) return;
    const ctx = el.getContext("2d");
    if (!ctx) return;

    const w = el.width;
    const h = el.height;
    const specks = Array.from({ length: COUNT }, () => spawn(w, h, true));
    let last = performance.now();
    let raf = 0;

    const frame = (t: number) => {
      const dt = Math.min(0.05, (t - last) / 1000);
      last = t;
      ctx.clearRect(0, 0, w, h);
      for (const s of specks) {
        s.y -= s.vy * dt;
        s.x += Math.sin(t / 2400 + s.phase) * 0.12;
        if (s.y < -10) Object.assign(s, spawn(w, h, false));
        // Brighter near the top, where the light is.
        const lift = 1 - s.y / h;
        const alpha = s.base * (0.55 + 0.45 * Math.sin(t / 900 + s.phase)) * (0.35 + lift);
        ctx.beginPath();
        ctx.fillStyle = `rgba(140, 245, 154, ${alpha.toFixed(3)})`;
        ctx.shadowColor = "rgba(3, 230, 3, 0.8)";
        ctx.shadowBlur = 6;
        ctx.arc(s.x, s.y, s.r, 0, Math.PI * 2);
        ctx.fill();
      }
      raf = requestAnimationFrame(frame);
    };
    raf = requestAnimationFrame(frame);
    return () => cancelAnimationFrame(raf);
  }, []);

  return (
    <>
      <canvas ref={canvas} className="atmo-specks" width={1920} height={1080} aria-hidden />
      <div className="atmo-grain" aria-hidden />
    </>
  );
}
