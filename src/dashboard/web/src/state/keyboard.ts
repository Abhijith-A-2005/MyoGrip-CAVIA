import type { GestureKey } from "../types/messages";
import { getState, setHeld, subscribe } from "./store";
import type { Transport } from "./ws";

const KEYS: readonly GestureKey[] = ["w", "a", "s", "d", "e"];

function isTyping(target: EventTarget | null) {
  const el = target as HTMLElement | null;
  return !!el && (el.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName));
}

/**
 * Keyboard EMG emulator in the browser, same rules as the pygame simulator: real key-down/up,
 * no auto-repeat, and every held key is released when the window loses focus.
 */
export function attachKeyboard(transport: Transport) {
  const held = new Set<GestureKey>();

  const send = (key: GestureKey, down: boolean) => {
    if (down) held.add(key);
    else held.delete(key);
    setHeld([...held]);
    transport.send({ type: "key", data: { key, down } });
  };

  const onDown = (ev: KeyboardEvent) => {
    const key = ev.key.toLowerCase() as GestureKey;
    if (!KEYS.includes(key) || ev.repeat || isTyping(ev.target) || ev.ctrlKey || ev.metaKey || ev.altKey) return;
    ev.preventDefault();
    if (!held.has(key)) send(key, true);
  };

  const onUp = (ev: KeyboardEvent) => {
    const key = ev.key.toLowerCase() as GestureKey;
    if (held.has(key)) send(key, false);
  };

  const releaseAll = () => [...held].forEach((key) => send(key, false));
  // Connection/boot changes require a fresh physical key-down, never a held-key replay.
  const generation = () => {
    const state = getState();
    return `${state.link}:${state.system?.controller}:${state.system?.hand_link.status}:${state.system?.keyboard_ready}`;
  };
  let currentGeneration = generation();
  const unsubscribe = subscribe(() => {
    const next = generation();
    if (next !== currentGeneration) {
      currentGeneration = next;
      releaseAll();
    }
  });
  const heartbeat = window.setInterval(() => {
    transport.send({ type: "key_state", data: { keys: [...held] } });
  }, 100);
  const onVisibility = () => document.hidden && releaseAll();

  window.addEventListener("keydown", onDown);
  window.addEventListener("keyup", onUp);
  window.addEventListener("blur", releaseAll);
  document.addEventListener("visibilitychange", onVisibility);

  return () => {
    window.clearInterval(heartbeat);
    unsubscribe();
    releaseAll();
    window.removeEventListener("keydown", onDown);
    window.removeEventListener("keyup", onUp);
    window.removeEventListener("blur", releaseAll);
    document.removeEventListener("visibilitychange", onVisibility);
  };
}
