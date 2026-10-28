"""Run all serial regressions and exercise keyboard control of the real board FSM."""
import argparse
from pathlib import Path
import runpy
import sys

import serial

TEST_ROOT = Path(__file__).parent
menu_test = runpy.run_path(str(TEST_ROOT / "menu-link-check.py"))
keyboard_test = runpy.run_path(str(TEST_ROOT / "keyboard-link-check.py"))
MenuLink = menu_test["MenuLink"]


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


class SharedDriver:
    def __init__(self, link):
        self.link = link
        state = link.fresh_state()
        require(state.get("keyboard_wire", 0) >= 2,
                "Flash the shared-input checkpoint first")
        self.session = state["keyboard_session"] + 1
        require(self.session <= 0xFFFFFFFF, "Reset board: session counter exhausted")
        self.sequence = 1
        require(keyboard_test["request"](link, self.session, self.sequence, 0),
                "Keyboard release handshake failed")

    def mask(self, value):
        self.sequence += 1
        self.link.send(f"K {self.link.boot} {self.session} {self.sequence} {value}")
        ack = self.link.wait_json("MGKEYACK", lambda item:
                                 item["session"] == self.session
                                 and item["sequence"] == self.sequence)
        require(ack["boot"] == self.link.boot, "Board restarted during keyboard input")
        if not ack["accepted"]:
            state = self.link.fresh_state()
            details = {name: state.get(name) for name in (
                "state", "loaded", "revision", "keyboard_session",
                "keyboard_sequence", "keyboard_mask", "keyboard_connected")}
            raise RuntimeError(
                f"Keyboard packet rejected: sequence={self.sequence}, mask={value}; "
                f"ack={ack}; board={details}")

    def wait(self, predicate):
        return self.link.wait_json("MGSTATE", lambda value:
                                  value["boot"] == self.link.boot and predicate(value))

    def tap(self, value):
        before = self.link.fresh_state()
        self.mask(0)  # Rearm immediately before the press, after any idle wait.
        self.mask(value)
        self.mask(0)
        return self.wait(lambda state: state["gesture_seq"] > before["gesture_seq"]
                         and state.get("gesture_source") in ("keyboard", "both"))

    def home(self):
        for _ in range(3):
            state = self.link.fresh_state()
            if state["state"] == "HOME":
                return
            if state["returning"]:
                self.wait(lambda value: value["state"] == "FULL")
            else:
                state = self.tap(16)
                if state["returning"]:
                    self.wait(lambda value: value["state"] == "FULL")
        require(self.link.fresh_state()["state"] == "HOME", "Could not return HOME")

    def load(self, menu_id):
        self.mask(0)
        self.link.load_current(menu_id)

    def press(self, mask):
        before = self.link.fresh_state()
        self.mask(0)
        self.mask(mask)
        return self.wait(lambda state: state["gesture_seq"] > before["gesture_seq"])


def run(link):
    # Start the legacy packet tests in HOME, including when this test is rerun.
    control = SharedDriver(link)
    control.home()
    keyboard_test["run"](link)
    menu_test["run"](link)

    # The protocol regression replaces its session; open a newer released one.
    control = SharedDriver(link)
    control.home()
    control.load(910001)
    state = link.fresh_state()
    require(state["state"] == "ADAPTIVE" and state["loaded"] == 1,
            "Keyboard session did not preserve the loaded menu")
    print(f"PASS: menu available with EMG calibrated={state['calibrated']}")

    state = control.tap(4)
    require(state["state"] == "ADAPTIVE" and state["selected"] == 1,
            "S did not select the next grip")
    print("PASS: S selects next grip")
    state = control.tap(1)
    require(state["state"] == "ADAPTIVE" and state["selected"] == 0,
            "W did not select the previous grip")
    print("PASS: W selects previous grip")

    control.press(2)
    control.wait(lambda value: value["state"] == "CLOSING" and value["progress"] >= 0.04)
    print("PASS: A confirms and closes")
    control.mask(0)
    state = control.wait(lambda value: value["state"] == "HOLDING")
    closed_progress = state["progress"]
    require(closed_progress > 0, "Confirmed grip did not advance")
    print("PASS: releasing A holds progress")

    control.press(8)
    control.wait(lambda value: value["state"] == "OPENING"
                 and value["progress"] < closed_progress)
    control.mask(0)
    control.wait(lambda value: value["state"] == "HOLDING")
    print("PASS: D opens the confirmed grip")

    control.press(2)
    control.wait(lambda value: value["state"] == "CLOSING")
    # Intentionally send no heartbeat; the firmware must release the hold.
    state = control.wait(lambda value: value["keyboard_connected"] == 0
                         and value["state"] == "HOLDING")
    require(state["keyboard_mask"] == 0, "Expired hold still has active keys")
    print("PASS: heartbeat timeout stops keyboard-driven movement")

    control.tap(16)
    control.wait(lambda value: value["state"] == "FULL" and value["progress"] == 0)
    state = control.tap(16)
    require(state["state"] == "HOME", "E from FULL did not return HOME")
    print("PASS: E performs controlled return to FULL, then HOME")

    control.load(910002)
    state = control.tap(8)
    require(state["state"] == "FULL", "D from Adaptive did not open Full Menu")
    print("PASS: D opens Full Menu while navigating")

    control.tap(2)
    control.wait(lambda value: value["state"] == "HOLDING")
    control.mask(2 | 8)
    control.wait(lambda value: value["state"] == "HOLDING" and value["gate"] == 1)
    control.mask(0)
    control.wait(lambda value: value["state"] == "HOLDING" and value["gate"] == 0)
    print("PASS: A+D conflict holds until release")
    control.home()
    print("PASS: shared keyboard FSM (10 checks)")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True)
    parser.add_argument("--baud", type=int, default=115200)
    args = parser.parse_args()
    link = None
    try:
        link = MenuLink(args.port, args.baud)
        run(link)
        return 0
    except (RuntimeError, TimeoutError, ValueError, KeyError, serial.SerialException) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    finally:
        if link is not None:
            link.serial.close()


if __name__ == "__main__":
    sys.exit(main())
