import { useEffect, useState } from "react";
import { useDashboard } from "./store";

/** Seconds since the running rest window started (browser clock), or null when no rest is running. */
export function useRestSeconds(): number | null {
  const startedAt = useDashboard((s) => s.restStartedAt);
  const [now, setNow] = useState(0);

  useEffect(() => {
    if (startedAt == null) return;
    const update = () => setNow(performance.now());
    update();
    const id = window.setInterval(update, 250);
    return () => window.clearInterval(id);
  }, [startedAt]);

  return startedAt == null ? null : Math.max(0, now - startedAt) / 1000;
}
