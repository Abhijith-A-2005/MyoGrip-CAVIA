"""Python reference of the MyoGrip interaction FSM (assets/figures/emg-fsm.png).

Pure and deterministic: no clock inside. Callers feed discrete events (menu mode),
continuous activity (actuation mode) and `tick(dt)` to advance grip progression.
Behaviour is pinned by tests/fsm/vectors.json, shared with the firmware FSM.
"""

from __future__ import annotations

from cavia.core.config import FsmConfig
from cavia.core.contracts import (
    Activity, EmgEvent, FsmState, FsmStatus, Grip, MenuKind, MenuPolicy, MenuProposal,
)
from cavia.core.grips import full_menu

MENU_STATES = (FsmState.ADAPTIVE, FsmState.FULL)
ACTUATION_STATES = (FsmState.CLOSING, FsmState.HOLDING, FsmState.OPENING)


class MyoGripFsm:
    def __init__(self, config: FsmConfig | None = None, full: list[Grip] | None = None):
        self.config = config or FsmConfig()
        for name in ("close_speed", "open_speed", "he_return_speed"):
            # A zero speed would trap the hand mid-grip (HE could never finish opening).
            if not getattr(self.config, name) > 0:
                raise ValueError(f"FsmConfig.{name} must be > 0")
        self.full: list[Grip] = list(full) if full is not None else full_menu()
        self.progress = 0.0
        self.reset()

    def reset(self) -> None:
        """Return to CAVIA Home and forget the menu snapshot. Progress is kept (hand position),
        so this is only safe with the hand open; use abort() from outside the FSM."""
        self.state = FsmState.HOME
        self.menu_id: int | None = None
        self.adaptive: list[Grip] = []
        self.selected = 0
        self.wait_release = False
        self.active_grip: Grip | None = None
        self.confirmed_from: MenuKind | None = None
        self.returning = False
        self.return_to = FsmState.FULL
        self.last_event: str | None = None

    # ---- inputs -------------------------------------------------------------

    def load_menu(self, proposal: MenuProposal) -> bool:
        """Adaptive menu ready. Only accepted in HOME: an open menu is a frozen snapshot."""
        if self.state is not FsmState.HOME:
            return False
        self.menu_id = proposal.menu_id
        self.full = list(proposal.full_menu)
        self.adaptive = list(proposal.items)
        self.selected = 0
        self.wait_release = False
        self.last_event = "MENU_READY"
        # Manual-cycling condition (and an empty proposal) has only the Full Menu.
        if proposal.policy is MenuPolicy.FULL_MENU or not self.adaptive:
            self.state = FsmState.FULL
        else:
            self.state = FsmState.ADAPTIVE
        return True

    def on_event(self, event: EmgEvent) -> None:
        """Discrete gesture. Only meaningful in the menus, plus HE during actuation."""
        self.last_event = event.value

        if self.state in MENU_STATES:
            items = self.current_items()
            if event is EmgEvent.SF:
                self.selected = (self.selected + 1) % len(items)
            elif event is EmgEvent.SE:
                self.selected = (self.selected - 1) % len(items)
            elif event is EmgEvent.LF:
                self.active_grip = items[self.selected]
                self.confirmed_from = self.menu_kind()
                # The confirming flexion may continue straight into closing (D16).
                self.state = FsmState.HOLDING
                self.wait_release = False
            elif event is EmgEvent.LE and self.state is FsmState.ADAPTIVE:
                self.state = FsmState.FULL
                self.selected = 0
            elif event is EmgEvent.HE:
                self.reset()
                self.last_event = EmgEvent.HE.value
            return

        if self.state in ACTUATION_STATES and event is EmgEvent.HE and not self.returning:
            # HE is the only way out of actuation: controlled opening, then Full Menu (see tick).
            self._start_return(FsmState.FULL)

    def abort(self) -> None:
        """Experimenter abort (BLE HOME): go to CAVIA Home, opening the hand first if a grip is active."""
        self.last_event = "ABORT"
        if self.state in ACTUATION_STATES:
            self._start_return(FsmState.HOME)
        else:
            self.reset()
            self.last_event = "ABORT"

    def _start_return(self, destination: FsmState) -> None:
        self.state = FsmState.OPENING
        self.returning = True
        self.return_to = destination
        self.wait_release = False

    def on_activity(self, activity: Activity) -> None:
        """Continuous flexor/extensor activity during actuation. Ignored elsewhere."""
        if self.state not in ACTUATION_STATES or self.returning:
            return
        self.last_event = activity.value

        if activity is Activity.REST:
            self.state = FsmState.HOLDING
            self.wait_release = False
        elif activity is Activity.INVALID:
            # Stop movement and require rest before accepting activity again.
            self.state = FsmState.HOLDING
            self.wait_release = True
        elif self.wait_release:
            return
        elif activity is Activity.FLEX_ACTIVE:
            self.state = FsmState.CLOSING
        elif activity is Activity.EXT_ACTIVE:
            self.state = FsmState.OPENING

    def tick(self, dt: float) -> None:
        """Advance constant-speed grip progression by dt seconds."""
        dt = max(0.0, dt)  # a clock glitch must never move the hand backwards
        if self.state is FsmState.CLOSING:
            self.progress = min(1.0, self.progress + self.config.close_speed * dt)
        elif self.state is FsmState.OPENING:
            speed = self.config.he_return_speed if self.returning else self.config.open_speed
            self.progress = max(0.0, self.progress - speed * dt)
            # Fully open stays in actuation so the user can close again (D16); only an HE
            # return ends the grip and offers the Full Menu.
            if self.returning and self.progress <= 0.0:
                if self.return_to is FsmState.HOME:
                    self.reset()
                    return
                self.state = FsmState.FULL
                self.selected = 0
                self.returning = False
                self.wait_release = False
                self.active_grip = None
                self.confirmed_from = None

    # ---- outputs ------------------------------------------------------------

    def menu_kind(self) -> MenuKind | None:
        if self.state is FsmState.ADAPTIVE:
            return MenuKind.ADAPTIVE
        if self.state is FsmState.FULL:
            return MenuKind.FULL
        return self.confirmed_from

    def current_items(self) -> list[Grip]:
        if self.state is FsmState.ADAPTIVE:
            return self.adaptive
        if self.state is FsmState.FULL:
            return self.full
        return []

    def selected_grip(self) -> Grip | None:
        items = self.current_items()
        return items[self.selected] if items else self.active_grip

    def status(self, ts: float) -> FsmStatus:
        return FsmStatus(
            ts=ts,
            menu_id=self.menu_id,
            state=self.state,
            menu_kind=self.menu_kind(),
            selected_index=self.selected,
            selected_grip=self.selected_grip(),
            active_grip=self.active_grip,
            grip_progress=self.progress,
            wait_release=self.wait_release,
            last_event=self.last_event,
        )
