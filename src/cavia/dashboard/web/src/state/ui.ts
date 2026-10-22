import { useEffect, useSyncExternalStore } from "react";

// View-only state that never comes from the backend: current page and the experimenter drawer.

export type Route = "live" | "evaluation";

const routeOf = (): Route => (window.location.hash.startsWith("#/evaluation") ? "evaluation" : "live");

let drawerOpen = false;
const listeners = new Set<() => void>();
const notify = () => listeners.forEach((l) => l());

function subscribe(listener: () => void) {
  listeners.add(listener);
  window.addEventListener("hashchange", listener);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("hashchange", listener);
  };
}

/** Hash routes (#/ and #/evaluation) so the backend never needs SPA fallback rules. */
export const useRoute = () => useSyncExternalStore(subscribe, routeOf);
export const navigate = (route: Route) => {
  window.location.hash = route === "evaluation" ? "#/evaluation" : "#/";
};

export const useDrawer = () => useSyncExternalStore(subscribe, () => drawerOpen);
export const setDrawer = (open: boolean) => {
  if (drawerOpen === open) return;
  drawerOpen = open;
  notify();
};
export const toggleDrawer = () => setDrawer(!drawerOpen);

/** `` ` `` toggles the experimenter drawer anywhere (except while typing); Esc closes it. */
export function useDrawerShortcut() {
  useEffect(() => {
    const onKey = (ev: KeyboardEvent) => {
      const typing = ["INPUT", "TEXTAREA", "SELECT"].includes((ev.target as HTMLElement)?.tagName);
      if (ev.key === "`" && !typing) {
        ev.preventDefault();
        toggleDrawer();
      } else if (ev.key === "Escape") {
        setDrawer(false);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
}
