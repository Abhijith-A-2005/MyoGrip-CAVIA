"""Run manually against the flashed board, with other serial viewers closed."""
import argparse
import json
import sys
import time

import serial


class MenuLink:
    def __init__(self, port, baud):
        # Set modem lines before opening, avoiding an intentional board reset.
        self.serial = serial.Serial(port=None, baudrate=baud, timeout=0.2)
        self.serial.dtr = False
        self.serial.rts = False
        self.serial.port = port
        self.serial.open()
        self.buffer = bytearray()
        self.boot = None
        self.bad_frames = 0

    def next_line(self, deadline):
        while time.monotonic() < deadline:
            if b"\n" in self.buffer:
                line, _, tail = self.buffer.partition(b"\n")
                self.buffer = bytearray(tail)
                return line.decode("utf-8", errors="replace")
            self.buffer.extend(self.serial.read(max(1, self.serial.in_waiting)))
            if len(self.buffer) > 16384:
                raise RuntimeError("Serial output has no bounded line ending")
        raise TimeoutError("Timed out waiting for firmware output")

    def wait_json(self, marker, predicate=lambda value: True):
        deadline = time.monotonic() + 10
        last_bad = None
        while True:
            try:
                line = self.next_line(deadline)
            except TimeoutError:
                if last_bad is not None:
                    raise TimeoutError(
                        f"No complete {marker} frame received. "
                        f"Last damaged payload: {last_bad}") from None
                raise
            # A damaged line can contain a later, complete frame as well.
            for payload in line.split(marker + " ")[1:]:
                payload = payload.lstrip()
                try:
                    value, _ = json.JSONDecoder().raw_decode(payload)
                    if not isinstance(value, dict):
                        raise ValueError("Expected a JSON object")
                except ValueError as exc:
                    self.bad_frames += 1
                    last_bad = f"{payload[:360]!r} ({exc})"
                    if self.bad_frames <= 3:
                        print(f"WARN: damaged {marker} frame skipped: {exc}",
                              file=sys.stderr)
                    continue
                if predicate(value):
                    return value

    def fresh_state(self):
        self.serial.reset_input_buffer()
        self.buffer.clear()
        state = self.wait_json("MGSTATE")
        require(state.get("wire", 0) >= 2, "Flash the serial-menu checkpoint first")
        if self.boot is None:
            self.boot = state["boot"]
        require(state["boot"] == self.boot, "Board restarted during the test")
        return state

    def send(self, line):
        self.serial.write((line + "\r\n").encode("ascii"))
        self.serial.flush()

    def request(self, line, menu_id):
        self.send(line)
        ack = self.wait_json("MGACK", lambda value: value["menu_id"] == menu_id)
        require(ack["boot"] == self.boot, "Acknowledgement has a different boot ID")
        return ack

    def malformed(self, line):
        self.serial.reset_input_buffer()
        self.buffer.clear()
        self.send(line)
        deadline = time.monotonic() + 5
        while "Malformed menu packet rejected" not in self.next_line(deadline):
            pass

    def load_current(self, menu_id):
        # A real EMG event or acquisition reset can legitimately stale a proposal.
        for _ in range(12):
            state = self.fresh_state()
            if not state["menu_ready"]:
                continue
            line = packet(state, menu_id)
            ack = self.request(line, menu_id)
            if not ack["accepted"]:
                continue
            require(ack["revision"] == (state["revision"] + 1) & 0xFFFFFFFF,
                    "Accepted menu did not advance the revision")
            snapshot = self.wait_json(
                "MGSTATE", lambda value: value["menu_id"] == menu_id
                and value["revision"] == ack["revision"])
            require(snapshot["loaded"] == 1 and snapshot["selected"] == 0,
                    "Accepted snapshot has incorrect selection")
            require(snapshot["adaptive"] == [4, 2, 0, 0]
                    and snapshot["adaptive_count"] == 2
                    and snapshot["full"] == [1, 2, 3, 4]
                    and snapshot["full_count"] == 4,
                    "Acknowledged menu does not match the proposal")
            return line
        raise RuntimeError("No proposal accepted: keep the FSM in HOME or an idle menu")


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def packet(state, menu_id, boot=None, full="1 2 3 4"):
    if boot is None:
        boot = state["boot"]
    return f"@ {boot} {state['revision']} {menu_id} 0 2 4 2 0 0 4 {full}"


def run(link):
    original = link.load_current(900001)
    print("PASS: valid menu and exact acknowledged snapshot")
    require(link.request(original, 900001)["accepted"] == 0,
            "Replayed proposal was accepted")
    print("PASS: stale revision rejected")

    state = link.fresh_state()
    wrong_boot = state["boot"] ^ 1
    require(link.request(packet(state, 900002, boot=wrong_boot), 900002)["accepted"] == 0,
            "Wrong boot ID was accepted")
    print("PASS: wrong boot ID rejected")

    state = link.fresh_state()
    require(link.request(packet(state, 900003, full="1 1 3 4"), 900003)["accepted"] == 0,
            "Duplicate grips were accepted")
    print("PASS: invalid menu rejected")

    link.malformed("@ 1 2")
    print("PASS: truncated packet rejected")
    link.malformed("@ " + "rfxm" * 80)
    print("PASS: overlong packet rejected")
    link.load_current(900004)
    print("PASS: valid packet accepted after malformed input")
    print("PASS: serial menu link (7 checks)")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True, help="Board port, e.g. COM7")
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
