import { attachKeyboard } from "./keyboard";
import { startMock } from "./mock";
import { connectBackend, type Transport } from "./ws";

const params = () => new URLSearchParams(window.location.search);

/** Mock mode: `?mock=1`, or by default under `npm run dev`. Live backend: `?live=1`, or by default in a build. */
export function isMock(p = params()): boolean {
  return p.has("mock") || (import.meta.env.DEV && !p.has("live"));
}

/** Backend address defaults to the page's host on port 8000; override with `?backend=host:port`. */
function backendHost(p = params()): string {
  return p.get("backend") ?? `${window.location.hostname}:8000`;
}

export function connect(): { transport: Transport; dispose: () => void } {
  const p = params();
  const transport = isMock(p) ? startMock(p) : connectBackend(`ws://${backendHost(p)}/ws`);
  const detachKeys = attachKeyboard(transport);
  return {
    transport,
    dispose: () => {
      detachKeys();
      transport.close();
    },
  };
}

export function videoUrl(): string | null {
  return isMock() ? null : `http://${backendHost()}/video`;
}
