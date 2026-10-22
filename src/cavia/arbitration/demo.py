"""Keyboard simulator adapter for CAVIA arbitration.

The existing FSM still accepts new menus only from HOME.
"""

from __future__ import annotations

import argparse
from dataclasses import replace
import json
import math
import uuid

from cavia.core.contracts import (
    FsmState,
    MenuKind,
    MenuPolicy,
)
from cavia.fsm.machine import (
    ACTUATION_STATES,
    MENU_STATES,
    MyoGripFsm,
)
from cavia.fsm.sim import (
    SimApp,
    draw,
    WIDTH,
    HEIGHT,
    MAX_TICK,
)

from .contracts import ArbitrationInput
from .engine import ArbitrationEngine
from .preferences import PreferenceStore


# Prototype eligibility gates; these do not measure contact.
ACCEPT_AFTER_SECONDS = 2.0
ACCEPT_AFTER_PROGRESS = 0.2


class ArbitrationSimApp(SimApp):
    def __init__(
        self,
        engine: ArbitrationEngine,
        request: ArbitrationInput,
    ):
        self.engine = engine
        self.request = request
        self.decision = None

        self.pending_id: str | None = None
        self.confirm_elapsed = 0.0
        self.max_progress = 0.0

        super().__init__(
            MyoGripFsm(full=list(engine.available)),
            [],
            MenuPolicy.FULL_COMPATIBLE,
        )

    def load_menu(self) -> None:
        if (
            self.fsm.state is not FsmState.HOME
            or self.keys.held
        ):
            self.note(
                "Menu load needs HOME and released keys"
            )
            return

        decision = self.engine.propose(self.request)

        if self.fsm.load_menu(decision.proposal):
            self.decision = decision
            self.menu_id = decision.proposal.menu_id
            self._prev_state = self.fsm.state

            self.note(
                f"menu #{self.menu_id}: "
                f"{decision.ranking_source}"
            )

            print(
                json.dumps(decision.to_dict(), indent=2),
                flush=True,
            )

    def key_down(self, name: str) -> None:
        name = name.lower()

        # Mock vision/user controls, permitted only from HOME.
        if name in {"1", "2", "3", "u"}:
            if (
                self.fsm.state is not FsmState.HOME
                or self.keys.held
            ):
                self.note(
                    "Context change needs HOME and released keys"
                )
                return

            if name == "u":
                next_user = (
                    "2"
                    if self.request.user == "1"
                    else "1"
                )

                self.request = replace(
                    self.request,
                    user=next_user,
                )

            else:
                region = {
                    "1": "unknown",
                    "2": "handle",
                    "3": "body",
                }[name]

                self.request = replace(
                    self.request,
                    region=region,
                )

            self.load_menu()
            return

        before = self.fsm.state
        was_returning = self.fsm.returning

        # Retain the existing WASDE behaviour.
        super().key_down(name)

        if (
            before in MENU_STATES
            and self.fsm.state in ACTUATION_STATES
        ):
            self.pending_id = str(uuid.uuid4())

            # Attribute selection to the FSM's accepted menu.
            self.engine.confirm(
                self.fsm.menu_id,
                self.fsm.active_grip,
                self.pending_id,
                from_full_menu=(
                    self.fsm.confirmed_from is MenuKind.FULL
                ),
            )

            self.confirm_elapsed = 0.0
            self.max_progress = 0.0

            self.note(
                "Selection pending; eligibility gate running"
            )

        if not was_returning and self.fsm.returning:
            self.cancel_pending()

    def step(self, dt: float) -> None:
        dt = (
            min(max(dt, 0.0), MAX_TICK)
            if math.isfinite(dt)
            else 0.0
        )

        super().step(dt)

        if (
            self.pending_id
            and self.fsm.state in ACTUATION_STATES
            and not self.fsm.returning
        ):
            self.confirm_elapsed += dt

            self.max_progress = max(
                self.max_progress,
                self.fsm.progress,
            )

            eligible = (
                self.confirm_elapsed >= ACCEPT_AFTER_SECONDS
                and self.max_progress >= ACCEPT_AFTER_PROGRESS
            )

            if eligible:
                row = self.engine.finish(
                    self.pending_id,
                    "accepted",
                )

                learned = (
                    row["compatible"]
                    and not row["instructed"]
                )

                self.note(
                    "Preference saved once"
                    if learned
                    else "Override logged; no preference update"
                )

                self.pending_id = None

    def cancel_pending(self) -> None:
        if self.pending_id:
            self.engine.finish(
                self.pending_id,
                "cancelled",
            )

            self.pending_id = None

            self.note(
                "Pending selection cancelled; not learned"
            )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__
    )

    parser.add_argument("--user", default="1")
    parser.add_argument("--object", default="cup")
    parser.add_argument("--region", default="unknown")

    parser.add_argument(
        "--vision-confidence",
        type=float,
        default=None,
    )

    # Keep synthetic feedback separate from real user history.
    parser.add_argument(
        "--db",
        default="data/arbitration/demo.sqlite3",
    )

    parser.add_argument(
        "--print-menu",
        action="store_true",
        help="Print one proposal without opening the GUI",
    )

    parser.add_argument(
        "--history",
        action="store_true",
        help="Show this user's recorded selections",
    )

    args = parser.parse_args()

    request = ArbitrationInput(
        args.user,
        args.object,
        args.region,
        args.vision_confidence,
    )

    with PreferenceStore(args.db) as store:
        engine = ArbitrationEngine(store)

        if args.history:
            print(
                json.dumps(
                    store.history(request.user),
                    indent=2,
                )
            )
            return

        if args.print_menu:
            print(
                json.dumps(
                    engine.propose(request).to_dict(),
                    indent=2,
                )
            )
            return

        try:
            import pygame
        except ImportError:
            raise SystemExit(
                'Install the simulator extra: '
                'python -m pip install -e ".[sim]"'
            )

        pygame.init()
        pygame.key.set_repeat()

        app = None

        try:
            # Scale the interface when the user resizes the window.
            window = pygame.display.set_mode(
                (WIDTH, HEIGHT + 92),
                pygame.RESIZABLE,
            )
            screen = pygame.Surface((WIDTH, HEIGHT + 92)).convert()

            pygame.display.set_caption(
                "CAVIA arbitration - keyboard simulation"
            )

            fonts = (
                pygame.font.Font(None, 40),
                pygame.font.Font(None, 30),
                pygame.font.Font(None, 22),
            )

            clock = pygame.time.Clock()
            app = ArbitrationSimApp(engine, request)

            while not app.quit:
                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        app.quit = True

                    elif event.type == pygame.VIDEORESIZE:
                        window = pygame.display.set_mode(
                            (max(1, event.w), max(1, event.h)),
                            pygame.RESIZABLE,
                        )

                    elif event.type == pygame.KEYDOWN:
                        app.key_down(
                            pygame.key.name(event.key)
                        )

                    elif event.type == pygame.KEYUP:
                        app.key_up(
                            pygame.key.name(event.key)
                        )

                    elif event.type == pygame.WINDOWFOCUSLOST:
                        app.focus_lost()

                if app.quit:
                    break

                app.step(clock.tick(60) / 1000.0)

                # Reuse the existing simulator's drawing function.
                draw(app, screen, fonts)

                decision = app.decision

                lines = [
                    (
                        f"User {app.request.user} | "
                        f"{app.request.object} / "
                        f"{app.request.region} | simulated context"
                    ),
                    (
                        "HOME: 1 object only | 2 handle | 3 body | "
                        "U user 1/2 | M same context"
                    ),
                    (
                        f"{decision.proposal.policy.value} | "
                        f"{decision.reason}"
                        if decision
                        else "No menu"
                    ),
                    (
                        "History: accepted after 2 s and progress >= 0.2; "
                        "not a physical success measurement"
                    ),
                ]

                for index, line in enumerate(lines):
                    rendered = fonts[2].render(
                        line,
                        True,
                        (210, 215, 225),
                    )

                    screen.blit(
                        rendered,
                        (24, HEIGHT + index * 21),
                    )

                # Scale the finished interface to the current window size.
                window_width, window_height = window.get_size()
                scale = min(
                    window_width / screen.get_width(),
                    window_height / screen.get_height(),
                )
                scaled_size = (
                    max(1, int(screen.get_width() * scale)),
                    max(1, int(screen.get_height() * scale)),
                )
                preview = pygame.transform.smoothscale(screen, scaled_size)

                window.fill((24, 26, 31))
                window.blit(
                    preview,
                    (
                        (window_width - scaled_size[0]) // 2,
                        (window_height - scaled_size[1]) // 2,
                    ),
                )
                pygame.display.flip()

        finally:
            if app is not None:
                app.cancel_pending()

            pygame.quit()


if __name__ == "__main__":
    main()