import type { ClientMessage, ServerMessage } from "../types/messages";
import { applyMessage, setLink } from "./store";

const RETRY_MS = 1000;

export type Transport = { send: (msg: ClientMessage) => void; close: () => void };

/** WebSocket to the CAVIA backend. Reconnects every second and resyncs from the server snapshot. */
export function connectBackend(url: string): Transport {
  let socket: WebSocket | null = null;
  let closed = false;
  let timer: number | undefined;

  const open = () => {
    socket = new WebSocket(url);
    socket.onopen = () => setLink("open");
    socket.onmessage = (ev) => {
      try {
        applyMessage(JSON.parse(ev.data) as ServerMessage);
      } catch (err) {
        console.warn("[ws] ignored malformed message", err);
      }
    };
    socket.onclose = () => {
      if (closed) return;
      setLink("reconnecting");
      timer = window.setTimeout(open, RETRY_MS);
    };
  };
  open();

  return {
    send: (msg) => {
      if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify(msg));
    },
    close: () => {
      closed = true;
      setLink("reconnecting");
      window.clearTimeout(timer);
      socket?.close();
    },
  };
}
