"""Interactive FSM simulator: mock CAVIA menu + keyboard EMG, no hardware.

    python -m keyboard_sim.fsm.sim --menu LATERAL,PINCH

Opens a window (needs real key press/release events). Install with: pip install -e ".[sim]"
"""

from __future__ import annotations

import argparse
import time
from collections import deque

from cavia.core.config import load_config
from cavia.core.contracts import (
    Condition, EmgEvent, FsmState, Grip, MenuConfidence, MenuContext, MenuPolicy, MenuProposal,
)
from cavia.core.grips import GRIP_LIBRARY, full_menu
from keyboard_sim.emg.keyboard import GESTURE_KEYS, HELP, KeyboardEmg
from keyboard_sim.fsm.machine import ACTUATION_STATES, MyoGripFsm

WIDTH, HEIGHT = 980, 560
MAX_TICK = 0.1
BG, PANEL, TEXT, MUTED = (24, 26, 31), (36, 39, 46), (230, 232, 236), (140, 146, 158)
ACCENT = (90, 160, 255)
STATE_COLORS = {
    FsmState.HOME: (140, 146, 158),
    FsmState.ADAPTIVE: (90, 160, 255),
    FsmState.FULL: (170, 120, 255),
    FsmState.CLOSING: (255, 150, 60),
    FsmState.HOLDING: (240, 200, 70),
    FsmState.OPENING: (80, 200, 120),
}


def mock_proposal(items: list[Grip], policy: MenuPolicy, menu_id: int) -> MenuProposal:
    return MenuProposal(
        ts=time.monotonic(), menu_id=menu_id, condition=Condition.C3_ADAPTIVE,
        context=MenuContext("mock", "mock", 1.0), policy=policy,
        items=items, scores=[1.0 / len(items)] * len(items),
        confidence=MenuConfidence(), full_menu=full_menu(),
    )


class SimApp:
    """Simulation logic, independent of the window so it can be driven by tests."""

    def __init__(self, fsm: MyoGripFsm, items: list[Grip], policy: MenuPolicy):
        self.fsm = fsm
        self.items = items
        self.policy = policy
        self.keys = KeyboardEmg()
        self.menu_id = 0
        self.log: deque[str] = deque(maxlen=9)
        self.started = time.monotonic()
        self.quit = False
        self._prev_state = fsm.state
        self.load_menu()

    def note(self, text: str) -> None:
        self.log.appendleft(f"{time.monotonic() - self.started:6.1f}s  {text}")

    def load_menu(self) -> None:
        if self.fsm.state is not FsmState.HOME:
            self.note("M ignored: not at HOME")
            return
        self.menu_id += 1
        self.fsm.load_menu(mock_proposal(self.items, self.policy, self.menu_id))
        self.note(f"menu #{self.menu_id} -> {self.fsm.state.value}")
        self._prev_state = self.fsm.state

    def key_down(self, name: str) -> None:
        name = name.lower()
        if name in ("q", "escape"):
            self.quit = True
        elif name == "m":
            self.load_menu()
        else:
            event = self.keys.press(name)
            if event is not None:
                self.fsm.on_event(event)
                if event is EmgEvent.INVALID:
                    self.note("INVALID: another key held")

    def key_up(self, name: str) -> None:
        self.keys.release(name)

    def focus_lost(self) -> None:
        if self.keys.held:
            self.note("focus lost: keys released")
        self.keys.release_all()

    def step(self, dt: float) -> None:
        # Activity is a continuous stream on the device; feed the held-key state every tick.
        self.fsm.on_activity(self.keys.activity())
        # A stalled window (dragging, suspend) must not jump the hand in one tick.
        self.fsm.tick(min(dt, MAX_TICK))
        if self.fsm.state is not self._prev_state:
            grip = self.fsm.active_grip.name if self.fsm.active_grip else "-"
            self.note(f"{self._prev_state.value} -> {self.fsm.state.value}  "
                      f"{grip}  p={self.fsm.progress:.2f}")
            self._prev_state = self.fsm.state


def draw(app: SimApp, screen, fonts) -> None:
    import pygame

    big, mid, small = fonts
    fsm = app.fsm
    screen.fill(BG)

    def text(s, pos, font=mid, color=TEXT):
        screen.blit(font.render(s, True, color), pos)

    state_color = STATE_COLORS[fsm.state]
    text("MyoGrip FSM simulator", (24, 18), small, MUTED)
    pygame.draw.rect(screen, state_color, (24, 44, 220, 44), border_radius=8)
    text(fsm.state.value, (38, 52), big, BG)
    flags = [f for f, on in (("STOPPED: release all keys", fsm.wait_release),
                             ("RETURNING TO OPEN", fsm.returning)) if on]
    text("   ".join(flags), (258, 58), small, (255, 120, 120))

    # Menu panel: vertical list, as on the real interface.
    pygame.draw.rect(screen, PANEL, (24, 104, 360, 300), border_radius=8)
    items = fsm.current_items()
    if items:
        header = "ADAPTIVE MENU" if fsm.state is FsmState.ADAPTIVE else "FULL MENU (all calibrated)"
        text(header, (40, 116), small, MUTED)
        for i, grip in enumerate(items):
            y = 146 + i * 48
            if i == fsm.selected:
                pygame.draw.rect(screen, ACCENT, (36, y - 6, 336, 40), border_radius=6)
            text(GRIP_LIBRARY[grip].label, (52, y), mid, BG if i == fsm.selected else TEXT)
    elif fsm.state in ACTUATION_STATES:
        text("ACTIVE GRIP", (40, 116), small, MUTED)
        text(GRIP_LIBRARY[fsm.active_grip].label, (40, 146), big)
        text(f"from {fsm.confirmed_from.value.lower()} menu", (40, 186), small, MUTED)
    else:
        text("CAVIA HOME", (40, 116), small, MUTED)
        text("Waiting for a menu - press M", (40, 146), mid, MUTED)

    # Grip progress: vertical bar, 0 = open (bottom) to 1 = closed (top).
    bx, by, bw, bh = 404, 104, 60, 300
    pygame.draw.rect(screen, PANEL, (bx, by, bw, bh), border_radius=8)
    fill = round(bh * fsm.progress)
    if fill:
        pygame.draw.rect(screen, state_color, (bx, by + bh - fill, bw, fill), border_radius=8)
    text(f"{fsm.progress:.2f}", (bx + 6, by + bh + 8), mid)
    text("closed", (bx + 70, by), small, MUTED)
    text("open", (bx + 70, by + bh - 18), small, MUTED)

    # Held keys and the EMG signal they stand for.
    kx = 548
    text("KEYS HELD", (kx, 104), small, MUTED)
    for i, key in enumerate(GESTURE_KEYS):
        held = key in app.keys.held
        rect = (kx + i * 52, 128, 44, 44)
        pygame.draw.rect(screen, ACCENT if held else PANEL, rect, border_radius=6)
        text(key.upper(), (rect[0] + 14, rect[1] + 10), mid, BG if held else TEXT)
    text(f"activity  {app.keys.activity().value}", (kx, 184), small)
    text(f"last      {fsm.last_event or '-'}", (kx, 206), small)
    text("EVENT LOG", (kx, 240), small, MUTED)
    for i, line in enumerate(app.log):
        text(line, (kx, 262 + i * 18), small, TEXT if i == 0 else MUTED)

    for i, line in enumerate(HELP):
        text(line, (24, 446 + i * 18), small, MUTED)


def parse_grips(text: str) -> list[Grip]:
    try:
        grips = [Grip[name.strip().upper()] for name in text.split(",") if name.strip()]
    except KeyError as e:
        raise SystemExit(f"Unknown grip {e}; choose from {[g.name for g in Grip if g is not Grip.OPEN]}")
    if not grips or Grip.OPEN in grips:
        raise SystemExit("--menu needs at least one grasp grip (OPEN is not a menu choice)")
    return grips


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--menu", default="LATERAL,PINCH", help="adaptive menu grips, comma-separated")
    parser.add_argument("--policy", default="TOP_TWO", choices=[p.value for p in MenuPolicy])
    parser.add_argument("--config", help="TOML config overriding [fsm] speeds")
    parser.add_argument("--hz", type=float, default=60.0, help="FSM tick / redraw rate")
    args = parser.parse_args(argv)

    try:
        import pygame
    except ImportError:
        raise SystemExit('The simulator needs pygame-ce: pip install -e ".[sim]"')

    app = SimApp(MyoGripFsm(load_config(args.config).fsm), parse_grips(args.menu), MenuPolicy(args.policy))

    pygame.init()
    pygame.key.set_repeat()  # no auto-repeat: one press = one gesture
    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    pygame.display.set_caption("MyoGrip FSM simulator")
    fonts = (pygame.font.Font(None, 40), pygame.font.Font(None, 30), pygame.font.Font(None, 22))
    clock = pygame.time.Clock()

    try:
        while not app.quit:
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    app.quit = True
                elif ev.type == pygame.KEYDOWN:
                    app.key_down(pygame.key.name(ev.key))
                elif ev.type == pygame.KEYUP:
                    app.key_up(pygame.key.name(ev.key))
                elif ev.type == pygame.WINDOWFOCUSLOST:
                    app.focus_lost()
            app.step(clock.tick(args.hz) / 1000.0)
            draw(app, screen, fonts)
            pygame.display.flip()
    finally:
        pygame.quit()


if __name__ == "__main__":
    main()
