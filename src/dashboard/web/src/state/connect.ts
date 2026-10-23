import { attachKeyboard } from "./keyboard";
import { mockFrameUrl, mockHistory, startMock } from "./mock";
import type { ClientMessage, HistoryMsg } from "../types/messages";
import { connectBackend, type Transport } from "./ws";

let current: Transport | null = null;

/** Send a control message to whichever transport is active (backend or mock). */
export function send(msg: ClientMessage) {
  current?.send(msg);
}

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
  current = transport;
  const detachKeys = attachKeyboard(transport);
  return {
    transport,
    dispose: () => {
      detachKeys();
      transport.close();
      if (current === transport) current = null;
    },
  };
}

/** MJPEG stream from the backend, or the still mock frame in mock mode. */
export function videoUrl(): string {
  const p = params();
  return isMock(p) ? mockFrameUrl(p) : `http://${backendHost(p)}/video`;
}

/** One user's selection history, from the backend or generated in mock mode. */
export async function fetchHistory(user: string, signal?: AbortSignal): Promise<HistoryMsg> {
  const p = params();
  if (isMock(p)) return mockHistory(user);
  const res = await fetch(`http://${backendHost(p)}/api/history?user=${encodeURIComponent(user)}`, { signal });
  if (!res.ok) throw new Error(`History request failed (${res.status})`);
  return (await res.json()) as HistoryMsg;
}
