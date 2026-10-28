"""Check keyboard transport only; FSM keyboard control is the next checkpoint."""
import argparse
from pathlib import Path
import runpy
import sys
import time

import serial

# Reuse the tested serial reader, including its damaged-frame diagnostics.
MenuLink = runpy.run_path(str(Path(__file__).with_name("menu-link-check.py")))["MenuLink"]


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def request(link, session, sequence, mask, boot=None):
    if boot is None:
        boot = link.boot
    link.send(f"K {boot} {session} {sequence} {mask}")
    ack = link.wait_json("MGKEYACK", lambda value:
                         value["session"] == session and value["sequence"] == sequence)
    require(ack["boot"] == link.boot, "Board restarted during keyboard test")
    return ack["accepted"] == 1


def snapshot(link, session, sequence):
    return link.wait_json("MGSTATE", lambda value:
                          value.get("keyboard_session") == session
                          and value.get("keyboard_sequence") == sequence)


def run(link):
    state = link.fresh_state()
    require(state.get("keyboard_wire") == 1, "Flash the keyboard-protocol checkpoint first")
    session = state["keyboard_session"] + 1
    require(session < 0xFFFFFFFF, "Session counter exhausted; reset the board")

    require(not request(link, session, 1, 2), "Unreleased new session was accepted")
    print("PASS: held key rejected before release handshake")
    require(request(link, session, 1, 0), "Release handshake rejected")
    print("PASS: released session handshake")

    require(request(link, session, 2, 2), "Held key packet rejected")
    state = snapshot(link, session, 2)
    require(state["keyboard_mask"] == 2 and state["keyboard_connected"] == 1,
            "Held key snapshot is incorrect")
    print("PASS: held key acknowledged in telemetry")

    require(not request(link, session, 2, 0), "Duplicate sequence was accepted")
    print("PASS: duplicate sequence rejected")
    require(not request(link, session, 3, 0, boot=link.boot ^ 1),
            "Wrong boot ID was accepted")
    print("PASS: wrong boot ID rejected")
    require(request(link, session, 3, 0), "Key release rejected")
    state = snapshot(link, session, 3)
    require(state["keyboard_mask"] == 0, "Release did not clear held keys")
    print("PASS: key release acknowledged")

    newer = session + 1
    require(request(link, newer, 1, 0), "New session handshake rejected")
    require(not request(link, session, 4, 0), "Retired session was accepted")
    print("PASS: retired session rejected after replacement")

    require(request(link, newer, 2, 2), "New session held key rejected")
    state = link.wait_json("MGSTATE", lambda value:
                          value.get("keyboard_session") == newer
                          and value.get("keyboard_sequence") == 2
                          and value.get("keyboard_connected") == 0)
    require(state["keyboard_mask"] == 0, "Timeout did not clear held keys")
    print("PASS: held key cleared after heartbeat timeout")

    require(not request(link, newer, 3, 2), "Expired hold resumed without release")
    require(request(link, newer, 3, 0), "Release after timeout rejected")
    require(request(link, newer, 4, 2), "New press after release rejected")
    require(request(link, newer, 5, 0), "Final key release rejected")
    print("PASS: expired hold requires release before another press")

    link.send(f"K {link.boot} 0 1 0")
    deadline = time.monotonic() + 5
    while "Malformed keyboard packet rejected" not in link.next_line(deadline):
        pass
    require(request(link, newer, 6, 0), "Valid packet rejected after malformed input")
    print("PASS: malformed keyboard packet rejected; parser recovered")
    print("PASS: keyboard packet protocol (10 checks)")


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
