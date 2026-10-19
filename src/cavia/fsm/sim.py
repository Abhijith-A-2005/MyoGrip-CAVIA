"""Interactive FSM simulator: mock CAVIA menu + keyboard EMG, no hardware.

    python -m cavia.fsm.sim --menu LATERAL,PINCH
"""

from __future__ import annotations

import argparse
import sys
import time

from cavia.core.config import load_config
from cavia.core.contracts import (
    Activity, Condition, FsmState, Grip, MenuConfidence, MenuContext, MenuPolicy, MenuProposal,
)
from cavia.core.grips import full_menu
from cavia.emg.keyboard import HELP, KeyReader, key_to_input
from cavia.fsm.machine import ACTUATION_STATES, MyoGripFsm


def mock_proposal(items: list[Grip], policy: MenuPolicy, menu_id: int) -> MenuProposal:
    return MenuProposal(
        ts=time.monotonic(), menu_id=menu_id, condition=Condition.C3_ADAPTIVE,
        context=MenuContext("mock", "mock", 1.0), policy=policy,
        items=items, scores=[1.0 / len(items)] * len(items),
        confidence=MenuConfidence(), full_menu=full_menu(),
    )


def render(fsm: MyoGripFsm, latched: Activity) -> str:
    items = fsm.current_items()
    if items:
        menu = " ".join(f">{g.name}<" if i == fsm.selected else g.name for i, g in enumerate(items))
    else:
        menu = "-"
    filled = round(fsm.progress * 20)
    bar = "#" * filled + "." * (20 - filled)
    grip = fsm.active_grip.name if fsm.active_grip else "-"
    flags = " GATE" if fsm.wait_release else ""
    flags += " RETURN" if fsm.returning else ""
    activity = f" act={latched.value}" if fsm.state in ACTUATION_STATES else ""
    return (f"[{fsm.state.value:8}] {menu} | grip {grip} [{bar}] {fsm.progress:.2f}"
            f"{flags}{activity} | last {fsm.last_event or '-'}")


def parse_grips(text: str) -> list[Grip]:
    try:
        return [Grip[name.strip().upper()] for name in text.split(",") if name.strip()]
    except KeyError as e:
        raise SystemExit(f"Unknown grip {e}; choose from {[g.name for g in Grip]}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--menu", default="LATERAL,PINCH", help="adaptive menu grips, comma-separated")
    parser.add_argument("--policy", default="TOP_TWO", choices=[p.value for p in MenuPolicy])
    parser.add_argument("--config", help="TOML config overriding [fsm] speeds")
    parser.add_argument("--hz", type=float, default=50.0, help="FSM tick rate")
    args = parser.parse_args(argv)

    items = parse_grips(args.menu)
    policy = MenuPolicy(args.policy)
    fsm = MyoGripFsm(load_config(args.config).fsm)
    menu_id = 0
    latched = Activity.REST

    print(HELP, "\n")
    menu_id += 1
    fsm.load_menu(mock_proposal(items, policy, menu_id))

    period = 1.0 / args.hz
    last = time.monotonic()
    prev_state = None
    with KeyReader() as keys:
        while True:
            key = keys.read(period)
            now = time.monotonic()

            if key == "q":
                break
            if key == "m" and fsm.state is FsmState.HOME:
                menu_id += 1
                fsm.load_menu(mock_proposal(items, policy, menu_id))
            elif key is not None and (inp := key_to_input(key, now)) is not None:
                if inp.event is not None:
                    fsm.on_event(inp.event)
                else:
                    latched = inp.activity

            # Activity is a continuous stream on the device; replay the latched value every tick.
            if fsm.state not in ACTUATION_STATES:
                latched = Activity.REST
            fsm.on_activity(latched)
            fsm.tick(now - last)
            last = now

            if fsm.state is not prev_state:
                # Keep a scrolling history of state changes above the live line.
                sys.stdout.write("\r\x1b[K" + render(fsm, latched) + "\n")
                prev_state = fsm.state
            sys.stdout.write("\r\x1b[K" + render(fsm, latched))
            sys.stdout.flush()
    print()


if __name__ == "__main__":
    main()
