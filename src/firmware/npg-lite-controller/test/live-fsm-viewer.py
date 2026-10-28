"""View the real firmware FSM over USB serial. No laptop FSM is executed.

Install: python -m pip install pyserial
Run:     python test/live-fsm-viewer.py --port COM7
Close idf.py monitor first. Closing this window releases the port; the board
continues running independently. This tool never sends simulated EMG events.
"""

import argparse
from collections import deque
import json
import math
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk

GRIPS = {1: "POWER", 2: "PINCH", 3: "TRIPOD", 4: "LATERAL", -1: "NONE"}
STATES = ("HOME", "ADAPTIVE", "FULL", "HOLDING", "CLOSING", "OPENING")
COLORS = {"HOME": "#68748d", "ADAPTIVE": "#3478db", "FULL": "#9561d3",
          "HOLDING": "#b99022", "CLOSING": "#d8792e", "OPENING": "#279873"}
BG, PANEL, TEXT, MUTED = "#101620", "#1d2737", "#ecf1fa", "#a9b8cd"


def parse_snapshot(line):
    """Ignore IDF prefixes/ANSI suffixes and reject malformed snapshots."""
    marker = "MGSTATE "
    if marker not in line:
        return None
    try:
        data, _ = json.JSONDecoder().raw_decode(line.split(marker, 1)[1])
        if data["v"] != 1 or data["state"] not in STATES:
            return None
        if not math.isfinite(data["progress"]) or not 0 <= data["progress"] <= 1:
            return None
        for key in ("samples", "gesture_seq", "menu_id", "selected"):
            if type(data[key]) is not int or data[key] < 0:
                return None
        for key in ("calibrated", "armed", "loaded", "gate", "returning"):
            if data[key] not in (0, 1):
                return None
        for key in ("activity", "gesture"):
            if not isinstance(data[key], str):
                return None
        if data["active"] not in GRIPS:
            return None
        for key in ("adaptive", "full"):
            count = data[key + "_count"]
            if type(count) is not int or not 0 <= count <= 4:
                return None
            if not isinstance(data[key], list) or len(data[key]) != 4:
                return None
            if any(item not in (1, 2, 3, 4) for item in data[key][:count]):
                return None
        if data["state"] in ("ADAPTIVE", "FULL"):
            key = "adaptive" if data["state"] == "ADAPTIVE" else "full"
            if not data["loaded"] or data["selected"] >= data[key + "_count"]:
                return None
        return data
    except (KeyError, ValueError, TypeError):
        return None


class SerialLink:
    """Serial I/O stays off Tk's thread. Retain latest state and bounded logs."""

    def __init__(self, port, baud):
        self.port, self.baud = port, baud
        self.lock = threading.Lock()
        self.snapshot = None
        self.received = 0.0
        self.logs = deque(maxlen=100)
        self.error = None
        self.commands = queue.Queue(maxsize=8)
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True)

    def send(self, command):
        try:
            self.commands.put_nowait(command)
        except queue.Full:
            with self.lock:
                self.logs.append("Command queue full; try again.")

    def run(self):
        try:
            import serial
            # Set control lines before opening to avoid requesting a reset.
            with serial.Serial(port=None, baudrate=self.baud,
                               timeout=0.05, write_timeout=0.3) as device:
                device.dtr = False
                device.rts = False
                device.port = self.port
                device.open()
                pending = bytearray()
                while not self.stop.is_set():
                    try:
                        command = self.commands.get_nowait()
                    except queue.Empty:
                        command = None
                    if command is not None:
                        device.write((command + "\n").encode("ascii"))
                    pending.extend(device.read(min(device.in_waiting or 1, 4096)))
                    while b"\n" in pending:
                        raw, _, pending = pending.partition(b"\n")
                        line = raw.decode("utf-8", errors="replace").strip()
                        data = parse_snapshot(line)
                        with self.lock:
                            if data is not None:
                                self.snapshot = data
                                self.received = time.monotonic()
                            elif line:
                                self.logs.append(line)
                    if len(pending) > 16384:
                        pending.clear()
        except Exception as exc:
            with self.lock:
                self.error = f"Serial stopped: {exc}"


class Viewer:
    def __init__(self, root, link):
        self.root, self.link = root, link
        self.last_gesture_seq = None
        self.last_samples = None
        self.last_advance = 0.0
        self.seen_snapshot = None
        root.title("MyoGrip | Live firmware FSM - USB serial")
        root.geometry("1000x730")
        root.minsize(900, 690)
        root.configure(bg=BG)
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.text(root, "MyoGrip CAVIA / live firmware FSM", 20).pack(
            anchor="w", padx=22, pady=(16, 3))
        self.text(root, "Real EMG -> board FSM -> this view  |  Simulated grip progress; no servo output",
                  color=MUTED).pack(anchor="w", padx=22)
        self.status = self.text(root, "Waiting for firmware telemetry...", color="#ffd580")
        self.status.pack(anchor="w", padx=22, pady=10)

        strip = tk.Frame(root, bg=BG)
        strip.pack(fill="x", padx=22)
        self.cards = {}
        for state in STATES:
            card = tk.Label(strip, text=state, bg=PANEL, fg=MUTED,
                            font=("Segoe UI", 12, "bold"), pady=12)
            card.pack(side="left", expand=True, fill="x", padx=3)
            self.cards[state] = card

        body = tk.Frame(root, bg=BG)
        body.pack(fill="x", padx=22, pady=14)
        menu_panel = tk.Frame(body, bg=PANEL, width=360, height=230)
        menu_panel.pack(side="left", fill="both", expand=True, padx=(0, 14))
        menu_panel.pack_propagate(False)
        self.menu_title = self.text(menu_panel, "HOME / waiting for a menu", 14, bg=PANEL)
        self.menu_title.pack(anchor="w", padx=12, pady=10)
        self.menu_rows = []
        for _ in range(4):
            row = self.text(menu_panel, "", 14, bg=PANEL)
            row.pack(fill="x", padx=12, pady=2)
            self.menu_rows.append(row)
        info = tk.Frame(body, bg=BG)
        info.pack(side="left", fill="both", expand=True)
        self.activity = self.text(info, "Activity: --", 15)
        self.activity.pack(anchor="w", pady=4)
        self.gesture = self.text(info, "Last gesture: --", 15)
        self.gesture.pack(anchor="w", pady=4)
        self.flags = self.text(info, "", color="#ffd580")
        self.flags.pack(anchor="w", pady=4)
        self.progress_label = self.text(info, "Grip progress: --", 16)
        self.progress_label.pack(anchor="w", pady=(10, 6))
        self.progress = ttk.Progressbar(info, maximum=1.0, length=360)
        self.progress.pack(fill="x")
        self.text(info, "0 = fully open                         1 = fully closed",
                  10, MUTED).pack(anchor="w", pady=4)

        self.controls = tk.Frame(root, bg=BG)
        self.controls.pack(fill="x", padx=22)
        self.buttons = []
        for label, command in (("Rest / new session", "r"), ("Flexion", "f"),
                               ("Extension", "e"), ("High extension", "h"),
                               ("Validate", "v"), ("Cancel calibration", "x"),
                               ("Load demo menu", "m")):
            button = ttk.Button(self.controls, text=label,
                                command=lambda c=command: link.send(c))
            button.pack(side="left", padx=2)
            self.buttons.append((button, command))
        self.text(root, "Calibration: r -> f -> e -> h -> v. Wait for each DONE before the next capture.",
                  11, MUTED).pack(anchor="w", padx=22, pady=(10, 2))
        self.text(root, "SF next | SE previous | LF confirm | LE full menu | HE gradual return / exit",
                  11, MUTED).pack(anchor="w", padx=22, pady=(0, 8))
        self.log = tk.Text(root, height=9, bg=PANEL, fg=TEXT,
                           font=("Consolas", 10), wrap="word", state="disabled")
        self.log.pack(fill="both", expand=True, padx=22, pady=(0, 16))
        root.after(50, self.refresh)

    @staticmethod
    def text(parent, text, size=12, color=TEXT, bg=BG):
        return tk.Label(parent, text=text, font=("Segoe UI", size),
                        fg=color, bg=bg, anchor="w")

    def refresh(self):
        with self.link.lock:
            data, received = self.link.snapshot, self.link.received
            error = self.link.error
            lines = list(self.link.logs)
            self.link.logs.clear()
        now = time.monotonic()
        if data is not self.seen_snapshot and data is not None:
            if self.last_samples != data["samples"]:
                self.last_advance = received
            self.last_samples = data["samples"]
            self.seen_snapshot = data
            self.render(data)
        stale = data is None or now - received > 1.5 or now - self.last_advance > 1.5
        if error:
            message = error
        elif stale:
            message = "STALE / no advancing telemetry. Display is the last received board state."
        elif not data["calibrated"]:
            message = "Not calibrated. Capture r, f, e, h, then validate."
        elif not data["armed"]:
            message = "Calibration valid. Relax for at least 250 ms to arm."
        else:
            message = f"LIVE | {self.link.port} | sample {data['samples']} | menu #{data['menu_id']}"
        self.status.configure(text=message, fg="#ffd580" if stale or error else TEXT)
        for button, command in self.buttons:
            enabled = not stale and not error
            if command == "m":
                enabled = (enabled and data["calibrated"] and data["armed"]
                           and data["state"] == "HOME" and data["activity"] == "REST")
            button.configure(state="normal" if enabled else "disabled")
        if lines:
            self.log.configure(state="normal")
            self.log.insert("end", "\n".join(lines) + "\n")
            if int(self.log.index("end-1c").split(".")[0]) > 250:
                self.log.delete("1.0", "100.0")
            self.log.see("end")
            self.log.configure(state="disabled")
        self.root.after(50, self.refresh)

    def render(self, data):
        state = data["state"]
        for name, card in self.cards.items():
            card.configure(bg=COLORS[name] if name == state else PANEL,
                           fg=TEXT if name == state else MUTED)
        self.activity.configure(text="Activity: " + data["activity"])
        self.gesture.configure(text=f"Last gesture: {data['gesture']} (#{data['gesture_seq']})")
        flags = []
        if data["gate"]:
            flags.append("INVALID latched - relax to resume")
        if data["returning"]:
            flags.append("HE RETURN - opening to Full Menu")
        self.flags.configure(text="\n".join(flags))
        self.progress_label.configure(text=f"Grip progress: {100 * data['progress']:.1f}%")
        self.progress["value"] = data["progress"]
        items = []
        if state in ("ADAPTIVE", "FULL"):
            key = "adaptive" if state == "ADAPTIVE" else "full"
            items = data[key][:data[key + "_count"]]
            title = state + " MENU"
        elif state in ("HOLDING", "CLOSING", "OPENING"):
            title = "ACTIVE GRIP: " + GRIPS[data["active"]]
        else:
            title = "HOME / load demo menu after calibration"
        self.menu_title.configure(text=title)
        for index, row in enumerate(self.menu_rows):
            selected = index < len(items) and index == data["selected"]
            row.configure(text=("> " if selected else "  ") + GRIPS[items[index]]
                          if index < len(items) else "",
                          bg=COLORS[state] if selected else PANEL)

    def close(self):
        self.link.stop.set()
        self.link.thread.join(timeout=1.0)
        self.root.destroy()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True, help="e.g. COM7 or /dev/ttyACM0")
    parser.add_argument("--baud", type=int, default=115200)
    args = parser.parse_args()
    link = SerialLink(args.port, args.baud)
    root = tk.Tk()
    Viewer(root, link)
    link.thread.start()
    root.mainloop()


if __name__ == "__main__":
    main()
