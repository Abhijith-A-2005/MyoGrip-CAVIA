"""USB telemetry and guarded commands for the shared-input board firmware.

This module transports board state. It does not execute a hand FSM.
"""
from __future__ import annotations

from collections import deque
import json
import logging
import math
import queue
import sys
import threading
import time

log = logging.getLogger(__name__)
UINT32_MAX = 0xFFFFFFFF
STATES = {"HOME", "ADAPTIVE", "FULL", "HOLDING", "CLOSING", "OPENING"}
GRIPS = {-1: "NONE", 1: "POWER", 2: "PINCH", 3: "TRIPOD", 4: "LATERAL"}
FRESH_SECONDS = 1.5
COMMAND_SECONDS = 0.25
_WINDOWS_SERIAL = sys.platform == "win32"


def _uint32(value):
    return type(value) is int and 0 <= value <= UINT32_MAX


def _valid_snapshot(data):
    if not isinstance(data, dict):
        return False
    if (type(data["v"]) is not int or data["v"] != 1 or
            type(data["wire"]) is not int or data["wire"] != 3 or
            type(data["keyboard_wire"]) is not int or data["keyboard_wire"] != 2):
        return False
    if data["state"] not in STATES:
        return False
    if (type(data["progress"]) not in (int, float) or
            not math.isfinite(data["progress"]) or not 0 <= data["progress"] <= 1):
        return False
    for name in ("samples", "gesture_seq", "menu_id", "selected", "boot", "revision",
                 "rest", "keyboard_session", "keyboard_sequence", "keyboard_mask"):
        if not _uint32(data[name]):
            return False
    for name in ("calibrated", "armed", "loaded", "gate", "returning", "menu_ready",
                 "keyboard_connected"):
        if type(data[name]) is not int or data[name] not in (0, 1):
            return False
    if not data["boot"] or data["selected"] >= 4 or data["keyboard_mask"] > 31:
        return False
    if type(data["active"]) is not int or data["active"] not in GRIPS:
        return False
    if data["activity"] not in {"REST", "FLEX_ACTIVE", "EXT_ACTIVE", "INVALID", "UNCALIBRATED", "WARMUP"}:
        return False
    if data["gesture"] not in {"NONE", "SF", "SE", "LF", "LE", "HE", "REJECTED"}:
        return False
    if data["gesture_source"] not in {"device", "keyboard", "both"}:
        return False
    if data["armed"] and not data["calibrated"]:
        return False
    if data["keyboard_connected"] and (not data["keyboard_session"] or not data["keyboard_sequence"]):
        return False
    if not data["keyboard_connected"] and data["keyboard_mask"]:
        return False
    if not data["keyboard_session"] and data["keyboard_sequence"]:
        return False
    for name in ("adaptive", "full"):
        count, items = data[name + "_count"], data[name]
        if type(count) is not int or not 0 <= count <= 4:
            return False
        if not isinstance(items, list) or len(items) != 4:
            return False
        if any(type(item) is not int or item not in (0, 1, 2, 3, 4) for item in items):
            return False
        if any(item == 0 for item in items[:count]) or len(set(items[:count])) != count:
            return False
    if not set(data["adaptive"][:data["adaptive_count"]]).issubset(data["full"][:data["full_count"]]):
        return False
    state = data["state"]
    if state == "HOME":
        if data["loaded"] or data["active"] != -1 or data["progress"] != 0:
            return False
    else:
        if not data["loaded"] or not data["menu_id"] or not data["full_count"]:
            return False
        if state in ("ADAPTIVE", "FULL"):
            name = "adaptive" if state == "ADAPTIVE" else "full"
            if data["selected"] >= data[name + "_count"] or data["active"] != -1 or data["progress"] != 0:
                return False
        elif not any(data["selected"] < data[name + "_count"] and
                     data[name][data["selected"]] == data["active"] for name in ("adaptive", "full")):
            return False
    if data["returning"] and state != "OPENING":
        return False
    if data["gate"] and state != "HOLDING":
        return False
    if data["menu_ready"] and (state not in {"HOME", "ADAPTIVE", "FULL"} or data["keyboard_mask"]):
        return False
    return True


def parse_snapshot(line):
    """Accept complete known-version frames, even after damaged log fragments."""
    if not isinstance(line, str):
        return None
    for payload in reversed(line.split("MGSTATE ")[1:]):
        try:
            data, _ = json.JSONDecoder().raw_decode(payload.lstrip())
            if _valid_snapshot(data):
                return data
        except (KeyError, ValueError, TypeError, OverflowError):
            pass
    return None


def _words_line(code, words):
    if any(not _uint32(word) for word in words):
        raise ValueError("Wire values must be uint32 integers")
    return code + " " + " ".join(map(str, words)) + "\n"


def menu_line(snapshot, proposal, preserve=False):
    adaptive, full = list(proposal.items), list(proposal.full_menu)
    if (not 0 <= len(adaptive) <= 4 or not 1 <= len(full) <= 4 or
            any(type(item) is bool or not isinstance(item, int) or item not in (1, 2, 3, 4)
                for item in adaptive + full) or
            len(set(adaptive)) != len(adaptive) or len(set(full)) != len(full) or
            not set(adaptive).issubset(full)):
        raise ValueError("Invalid firmware menu grips")
    if not _uint32(proposal.menu_id) or not proposal.menu_id:
        raise ValueError("Menu ID must be a positive uint32")
    if proposal.policy.value not in {"FULL_COMPATIBLE", "TOP_TWO", "ONE_CONFIRM", "FULL_MENU"}:
        raise ValueError("Unknown menu policy")
    flags = int(proposal.policy.value == "FULL_MENU") | (2 if preserve else 0)
    adaptive, full = list(map(int, adaptive)), list(map(int, full))
    return _words_line("@", [snapshot["boot"], snapshot["revision"], proposal.menu_id, flags,
                              len(adaptive), *(adaptive + [0] * (4 - len(adaptive))),
                              len(full), *(full + [0] * (4 - len(full)))])


def next_keyboard_session(snapshot):
    session = snapshot["keyboard_session"]
    if not _uint32(session) or session == UINT32_MAX:
        raise ValueError("Keyboard session counter exhausted; reset the board")
    return session + 1


def keyboard_line(snapshot, session, sequence, mask):
    if not session or not sequence or not _uint32(mask) or mask > 31:
        raise ValueError("Invalid keyboard session, sequence or held mask")
    return _words_line("K", [snapshot["boot"], session, sequence, mask])


class DeviceLink:
    """One serial owner with freshness checks and no queued-command replay."""

    def __init__(self, port, baud=115200, *, clock=time.monotonic, serial_factory=None):
        self.port, self.baud, self.clock = port, baud, clock
        self.serial_factory = serial_factory
        self.lock = threading.Lock()
        self.packets = deque()
        self.commands = queue.Queue(maxsize=8)
        self.last = self.received = self.advanced = None
        self.connected = False
        self.error = "Waiting for shared-input firmware"
        self.calibration = ""
        self.discarded_frames = 0
        self.bytes_received = 0
        self.lines_received = 0
        self.last_serial_line = ""
        self.connections = 0
        self.epoch = 0
        self.stop_event = threading.Event()
        self.thread = None

    def _fresh(self):
        now = self.clock()
        return (self.connected and self.last is not None and self.received is not None
                and self.advanced is not None and 0 <= now - self.received < FRESH_SECONDS
                and 0 <= now - self.advanced < FRESH_SECONDS)

    def status(self):
        with self.lock:
            fresh = self._fresh()
            data = self.last or {}
            return {"status": "connected" if fresh else "stale" if self.connected else "disconnected",
                    "detail": "USB firmware FSM" if fresh else self.error,
                    "battery_pct": None, "calibrated": fresh and bool(data.get("calibrated")),
                    "armed": fresh and bool(data.get("armed")), "calibration": self.calibration,
                    "discarded_frames": self.discarded_frames, "connections": self.connections,
                    "bytes_received": self.bytes_received, "lines_received": self.lines_received}

    def drain(self):
        with self.lock:
            packets = list(self.packets)
            self.packets.clear()
            return packets

    def send(self, line):
        if not isinstance(line, str):
            raise ValueError("Command must be text")
        body = line.rstrip("\r\n")
        try:
            encoded = body.encode("ascii")
        except UnicodeEncodeError:
            raise ValueError("Commands must be ASCII") from None
        if not encoded or len(encoded) > 191 or "\r" in body or "\n" in body:
            raise ValueError("Send one bounded command at a time")
        words = body.split(" ")
        if body not in {"r", "f", "e", "h", "v", "x", "?", "m"}:
            size = {"@": 15, "K": 5}.get(words[0])
            if size is None or len(words) != size or any(not word.isdigit() for word in words[1:]):
                raise ValueError("Unsupported firmware command")
            if any(int(word) > UINT32_MAX for word in words[1:]):
                raise ValueError("Command integer exceeds uint32")
        with self.lock:
            if not self._fresh():
                raise ValueError("No fresh firmware telemetry")
            if words[0] in {"@", "K"} and int(words[1]) != self.last["boot"]:
                raise ValueError("Command targets an old board boot")
            item = (self.epoch, self.last["boot"], self.clock(), body + "\n")
            try:
                self.commands.put_nowait(item)
            except queue.Full:
                raise ValueError("Firmware command queue is full") from None

    def start(self):
        if self.thread is not None and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._run, name="cavia-usb", daemon=True)
        self.thread.start()

    def close(self):
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join(timeout=2)

    def _clear_commands(self):
        while True:
            try:
                self.commands.get_nowait()
            except queue.Empty:
                return

    def _accept(self, data):
        now = self.clock()
        with self.lock:
            previous = self.last
            if previous is not None and data["boot"] != previous["boot"]:
                self.epoch += 1
                self.packets.clear()
                self._clear_commands()
                self.advanced = None
                previous = None
            if previous is not None:
                delta = (data["samples"] - previous["samples"]) & UINT32_MAX
                if delta >= 0x80000000:
                    self.discarded_frames += 1
                    return
                if delta:
                    self.advanced = now
            if len(self.packets) >= 256:
                raise RuntimeError("Firmware telemetry queue overflow")
            self.last, self.received = data, now
            self.packets.append(data)
            self.error = ("Firmware telemetry stopped advancing" if self.advanced is not None
                          else "Waiting for firmware samples to advance")

    def _write_next(self, device):
        try:
            epoch, boot, created, line = self.commands.get_nowait()
        except queue.Empty:
            return
        with self.lock:
            valid = (self._fresh() and epoch == self.epoch and boot == self.last["boot"]
                     and 0 <= self.clock() - created < COMMAND_SECONDS)
        if valid:
            encoded = line.encode("ascii")
            if device.write(encoded) != len(encoded):
                raise OSError("Partial firmware command write")

    def _run(self):
        factory = self.serial_factory
        if factory is None:
            try:
                import serial
            except ImportError:
                with self.lock:
                    self.error = 'Install: python -m pip install -e ".[device]"'
                return
            factory = serial.Serial
        last_error = None
        while not self.stop_event.is_set():
            try:
                with factory(port=None, baudrate=self.baud, timeout=0.05, write_timeout=0.3) as device:
                    device.dtr = False
                    device.rts = False
                    device.port = self.port
                    device.open()
                    if _WINDOWS_SERIAL:
                        # usbser.sys may need explicit control writes after open.
                        # Reapply DTR after RTS, as in Espressif's workaround.
                        device.rts = False
                        device.dtr = False
                    self._clear_commands()
                    with self.lock:
                        self.epoch += 1
                        self.connections += 1
                        self.connected = True
                        self.last = self.received = self.advanced = None
                        self.packets.clear()
                        self.error = "Waiting for shared-input firmware"
                        self.calibration = ""
                    pending = bytearray()
                    while not self.stop_event.is_set():
                        self._write_next(device)
                        chunk = device.read(min(device.in_waiting or 1, 4096))
                        if chunk:
                            with self.lock:
                                self.bytes_received += len(chunk)
                            pending.extend(chunk)
                        while b"\n" in pending:
                            raw, _, pending = pending.partition(b"\n")
                            line = raw.decode("utf-8", errors="replace").strip()
                            with self.lock:
                                self.lines_received += 1
                                self.last_serial_line = line[:1024]
                            data = parse_snapshot(line)
                            if data is not None:
                                self._accept(data)
                                if self.status()["status"] == "connected":
                                    last_error = None
                            elif "MGSTATE " in line:
                                with self.lock:
                                    self.discarded_frames += 1
                            elif "MYOGRIP_CAL:" in line:
                                with self.lock:
                                    self.calibration = line.split("MYOGRIP_CAL:", 1)[1].strip()[:180]
                        if len(pending) > 16384:
                            raise ValueError("Oversized serial line")
            except Exception as exc:
                with self.lock:
                    self.error = str(exc)
                if str(exc) != last_error:
                    log.warning("NPG link: %s", exc)
                    last_error = str(exc)
            finally:
                with self.lock:
                    self.connected = False
                    self.epoch += 1
                    self.packets.clear()
                self._clear_commands()
            self.stop_event.wait(0.5)


def main():
    """Read-only hardware check: python -m cavia.server.device_link --port COM14."""
    import argparse
    parser = argparse.ArgumentParser(description=main.__doc__)
    parser.add_argument("--port", required=True)
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--seconds", type=float, default=10)
    args = parser.parse_args()
    if not math.isfinite(args.seconds) or not 0.5 <= args.seconds <= 60:
        parser.error("--seconds must be between 0.5 and 60")
    link = DeviceLink(args.port, args.baud)
    link.start()
    packets = []
    try:
        deadline = time.monotonic() + args.seconds
        while time.monotonic() < deadline:
            packets.extend(link.drain())
            time.sleep(0.05)
        packets.extend(link.drain())
        status = link.status()
        if status["status"] != "connected":
            print("FAIL: " + status["detail"])
            print(f"Bytes={status['bytes_received']}, lines={status['lines_received']}, "
                  f"discarded={status['discarded_frames']}, connections={status['connections']}")
            with link.lock:
                last_line = link.last_serial_line
            if last_line:
                print("LAST SERIAL LINE:", repr(last_line))
            return 1
        print("PASS: dashboard serial link receives advancing firmware state")
        print(f"Frames={len(packets)}, connections={status['connections']}, "
              f"discarded={status['discarded_frames']}, state={packets[-1]['state']}")
        return 0
    finally:
        link.close()


if __name__ == "__main__":
    raise SystemExit(main())
