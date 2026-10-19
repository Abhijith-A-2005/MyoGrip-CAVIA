import { useLayoutEffect, useState, type ReactNode } from "react";
import "./Stage.css";

export const STAGE_W = 1920;
export const STAGE_H = 1080;

/**
 * The dashboard is composed once at 1920x1080 and scaled to fit the window, so the projector
 * and a 1366x768 laptop show the same layout. Letterboxing fills any spare space with black.
 */
export function Stage({ children }: { children: ReactNode }) {
  const [fit, setFit] = useState({ scale: 1, x: 0, y: 0 });

  useLayoutEffect(() => {
    const update = () => {
      const scale = Math.min(window.innerWidth / STAGE_W, window.innerHeight / STAGE_H);
      setFit({
        scale,
        x: (window.innerWidth - STAGE_W * scale) / 2,
        y: (window.innerHeight - STAGE_H * scale) / 2,
      });
    };
    update();
    window.addEventListener("resize", update);
    return () => window.removeEventListener("resize", update);
  }, []);

  return (
    <div className="stage-viewport">
      <div
        className="stage"
        style={{ transform: `translate(${fit.x}px, ${fit.y}px) scale(${fit.scale})` }}
      >
        {children}
      </div>
    </div>
  );
}
