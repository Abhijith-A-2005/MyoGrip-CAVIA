#!/usr/bin/env python3
"""
record-log.py

Robust NPG-Lite BLE streamer with CSV fixes and automatic disconnect handling:
 - auto-connect (or supply --device-address)
 - try to request MTU=500 (if supported)
 - send "START" automatically
 - reassemble partial notifications into 7-byte samples
 - accumulate samples and write batches to CSV
 - flush & fsync after each batch write
 - write leftover partial samples on shutdown
 - exit automatically on BLE disconnect
 - save summary.txt with statistics in IST timezone
 - print BLE notification size for each packet received
 - hardcoded streaming duration timer (tracks data streaming time)

Usage:
    python record-log.py --outfile data.csv
"""

import argparse
import asyncio
import csv
import os
import sys
import time
from datetime import datetime
from typing import List, Optional

from bleak import BleakScanner, BleakClient

try:
    from zoneinfo import ZoneInfo  # Python 3.9+
    IST = ZoneInfo("Asia/Kolkata")
except ImportError:
    import pytz  # Fallback for Python < 3.9
    IST = pytz.timezone("Asia/Kolkata")

# ----- Default streaming duration -----
DEFAULT_STREAMING_DURATION_MINUTES = 10  # Default duration in MINUTES

# ----- Protocol constants (match firmware) -----
DATA_CHAR_UUID = "beb5483e-36e1-4688-b7f5-ea07361b26a8"
CONTROL_CHAR_UUID = "0000ff01-0000-1000-8000-00805f9b34fb"

NUM_CHANNELS = 3
SINGLE_SAMPLE_LEN = 7      # 1 counter + 3*2 bytes (big-endian)
BLOCK_COUNT = 25
NEW_PACKET_LEN = BLOCK_COUNT * SINGLE_SAMPLE_LEN
SAMP_RATE = 250.0          # per-channel sampling rate (Hz)

# ---- Utility: call attribute that may be property / callable / coroutine ----
async def call_maybe_async(obj, method_name: str, *args, **kwargs):
    attr = getattr(obj, method_name, None)
    if attr is None:
        raise AttributeError(f"{obj!r} has no attribute {method_name!r}")
    if callable(attr):
        res = attr(*args, **kwargs)
        if asyncio.iscoroutine(res):
            return await res
        return res
    return attr

# ---- CSV writer with flush+fsync ----
class CSVWriter:
    def __init__(self, path: str):
        # ensure directory exists
        d = os.path.dirname(os.path.abspath(path))
        if d and not os.path.exists(d):
            os.makedirs(d, exist_ok=True)
        # open file
        self.path = path
        try:
            self.f = open(path, "w", newline="")
        except Exception as e:
            raise RuntimeError(f"Failed to open CSV file {path!r}: {e}")
        self.writer = csv.writer(self.f)
        self.writer.writerow(["timestamp_unix", "counter", "ch0", "ch1", "ch2"])
        self.f.flush()
        try:
            os.fsync(self.f.fileno())
        except Exception:
            pass
        self.closed = False

    def write_batch(self, samples: List[dict], t_recv: float):
        """Write list of samples (any length) and flush+fsync after writing."""
        n = len(samples)
        if n == 0:
            return
        dt = 1.0 / SAMP_RATE
        for k, s in enumerate(samples):
            sample_time = t_recv - (n - 1 - k) * dt
            self.writer.writerow([f"{sample_time:.6f}", s["counter"], s["ch0"], s["ch1"], s["ch2"]])
        # flush & fsync so data is physically saved now
        try:
            self.f.flush()
            os.fsync(self.f.fileno())
        except Exception:
            # non-fatal: continue
            pass
        print(f"[CSV] Wrote {n} samples to {self.path} (last_counter={samples[-1]['counter']})")

    def close(self):
        if not self.closed:
            try:
                self.f.flush()
                try:
                    os.fsync(self.f.fileno())
                except Exception:
                    pass
                self.f.close()
            except Exception:
                pass
            self.closed = True

# ---- NPG client: handles reassembly, batching, and CSV writes ----
class NPGClient:
    def __init__(self, device_address: Optional[str] = None, name_prefix: str = "NPG", csv_out: Optional[str] = None, duration_minutes: int = DEFAULT_STREAMING_DURATION_MINUTES):
        self.device_address = device_address
        self.name_prefix = name_prefix
        self.client: Optional[BleakClient] = None
        self.rx_buffer = bytearray()          # staging buffer for partial sample bytes
        self.sample_accum: List[dict] = []    # accumulate parsed samples until BLOCK_COUNT
        self.csv_writer = CSVWriter(csv_out) if csv_out else None
        self.last_recv_time = None            # timestamp of last received notification
        self.duration_minutes = duration_minutes  # Streaming duration in minutes

        # Statistics tracking
        self.disconnected = False             # Flag set when BLE disconnects
        self.first_sample_time = None         # Unix timestamp of first sample
        self.last_sample_time = None          # Unix timestamp of last sample
        self.total_samples = 0                # Total samples received
        self.last_counter = None              # Last counter value (for detecting missing samples)
        self.missing_samples = 0              # Count of missing samples
        self.streaming_start_time = None      # When streaming actually started

    def _disconnected_callback(self, client):
        """Called when BLE connection is lost"""
        print("\n[DISCONNECT] BLE connection lost")
        self.disconnected = True

    async def find_device(self, timeout: float = 10.0) -> str:
        if self.device_address:
            return self.device_address
        print(f"Scanning for BLE devices with name prefix '{self.name_prefix}' ...")
        devices = await BleakScanner.discover(timeout=timeout)
        for d in devices:
            name = (d.name or "").upper()
            if name.startswith(self.name_prefix.upper()):
                print(f"Found matching device: {d.address} ({d.name})")
                return d.address
        raise RuntimeError("No matching NPG device found. Try increasing scan timeout or provide --device-address.")

    def _parse_one_sample(self, seven: bytes) -> dict:
        """Parse a 7-byte sample into dict"""
        if len(seven) != SINGLE_SAMPLE_LEN:
            raise ValueError("Invalid sample length")
        counter = seven[0]
        ch0 = (seven[1] << 8) | seven[2]
        ch1 = (seven[3] << 8) | seven[4]
        ch2 = (seven[5] << 8) | seven[6]
        return {"counter": counter, "ch0": ch0, "ch1": ch1, "ch2": ch2}

    def _update_statistics(self, sample: dict, t_recv: float):
        """Update tracking statistics for each sample"""
        # Track first and last sample times
        if self.first_sample_time is None:
            self.first_sample_time = t_recv
        self.last_sample_time = t_recv

        # Increment total samples
        self.total_samples += 1

        # Detect missing samples using counter (0-255 rolling)
        current_counter = sample["counter"]
        if self.last_counter is not None:
            expected_counter = (self.last_counter + 1) % 256
            if current_counter != expected_counter:
                # Calculate how many samples were missed
                if current_counter > expected_counter:
                    missed = current_counter - expected_counter
                else:
                    missed = (256 - expected_counter) + current_counter
                self.missing_samples += missed
                print(f"[WARNING] Detected {missed} missing samples (expected counter {expected_counter}, got {current_counter})")

        self.last_counter = current_counter

    def _handle_complete_batch(self, samples: List[dict], t_recv: float):
        # Update statistics for each sample in batch
        for sample in samples:
            self._update_statistics(sample, t_recv)

        # Calculate elapsed time since streaming started
        if self.streaming_start_time is not None:
            elapsed = t_recv - self.streaming_start_time
            elapsed_str = self._format_elapsed_time(elapsed)
        else:
            elapsed_str = "00:00:00"

        # print a compact summary and write to CSV if requested
        last = samples[-1]
        print(f"[BATCH] {len(samples)} samples; last_counter={last['counter']}; elapsed={elapsed_str}")
        if self.csv_writer:
            self.csv_writer.write_batch(samples, t_recv)


    def on_data_notify(self, sender, data: bytearray):
        """Notification callback: reassemble bytes into 7-byte samples, accumulate batches."""
        t_recv = time.time()
        self.last_recv_time = t_recv

        # Track streaming start time on first data received
        if self.streaming_start_time is None:
            self.streaming_start_time = t_recv
            print(f"[STREAMING] Started at {time.strftime('%H:%M:%S', time.localtime(t_recv))}")

        # Print notification size
        notification_size = len(data)
        print(f"[BLE] Notification received: {notification_size} bytes")

        # Append incoming bytes to staging buffer
        self.rx_buffer.extend(bytes(data))

        # While we have at least 7 bytes, parse one sample
        while len(self.rx_buffer) >= SINGLE_SAMPLE_LEN:
            seven = bytes(self.rx_buffer[:SINGLE_SAMPLE_LEN])
            # remove consumed bytes
            del self.rx_buffer[:SINGLE_SAMPLE_LEN]
            try:
                sample = self._parse_one_sample(seven)
            except Exception as e:
                print("Failed to parse 7-byte sample:", e, file=sys.stderr)
                continue
            self.sample_accum.append(sample)

            # If we have a full batch, handle it
            if len(self.sample_accum) >= BLOCK_COUNT:
                # take first BLOCK_COUNT samples
                batch = self.sample_accum[:BLOCK_COUNT]
                del self.sample_accum[:BLOCK_COUNT]
                # handle batch write
                self._handle_complete_batch(batch, t_recv)

    def on_control_notify(self, sender, data: bytearray):
        try:
            txt = bytes(data).decode("ascii", errors="replace")
            print(f"[CONTROL] {txt!r}")
        except Exception:
            print("[CONTROL] (binary)", bytes(data))

    def _format_time_ist(self, unix_timestamp: float) -> str:
        """Convert Unix timestamp to IST formatted string"""
        try:
            dt = datetime.fromtimestamp(unix_timestamp, tz=IST)
        except:
            # Fallback for pytz
            import pytz
            utc_dt = datetime.utcfromtimestamp(unix_timestamp).replace(tzinfo=pytz.UTC)
            dt = utc_dt.astimezone(IST)
        return dt.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3] + " IST"

    def _format_elapsed_time(self, seconds: float) -> str:
        """Format elapsed time as hh:mm:ss"""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"

    def write_summary(self, summary_path: str):
        """Write summary statistics to file"""
        try:
            with open(summary_path, "w") as f:
                f.write("=" * 60 + "\n")
                f.write("NPG-Lite Data Collection Summary\n")
                f.write("=" * 60 + "\n\n")

                # Sample counts
                f.write(f"Total samples received: {self.total_samples}\n")
                f.write(f"Samples per channel: {self.total_samples}\n")
                f.write(f"Missing samples detected: {self.missing_samples}\n\n")

                # Timestamps
                if self.first_sample_time and self.last_sample_time:
                    f.write(f"First sample received: {self._format_time_ist(self.first_sample_time)}\n")
                    f.write(f"Last sample received:  {self._format_time_ist(self.last_sample_time)}\n\n")

                    # Elapsed time
                    elapsed = self.last_sample_time - self.first_sample_time
                    f.write(f"Total time elapsed: {self._format_elapsed_time(elapsed)}\n")
                    f.write(f"Total time elapsed (seconds): {elapsed:.3f}\n\n")

                    # Data rate
                    actual_sample_rate = self.total_samples / elapsed if elapsed > 0 else 0
                    f.write(f"Expected sample rate: {SAMP_RATE} Hz\n")
                    f.write(f"Actual sample rate: {actual_sample_rate:.2f} Hz\n")
                else:
                    f.write("No samples were received.\n")

                f.write("\n" + "=" * 60 + "\n")

            print(f"\n[SUMMARY] Statistics saved to {summary_path}")
        except Exception as e:
            print(f"[ERROR] Failed to write summary: {e}", file=sys.stderr)

    async def connect_and_start(self):
        addr = await self.find_device()
        print("Connecting to", addr)

        # Create client with disconnect callback
        self.client = BleakClient(addr, disconnected_callback=self._disconnected_callback)
        await call_maybe_async(self.client, "connect")

        # detect connection (property or callable)
        is_conn_attr = getattr(self.client, "is_connected", None)
        if callable(is_conn_attr):
            try:
                is_conn = await is_conn_attr()
            except Exception:
                is_conn = bool(getattr(self.client, "is_connected", False))
        else:
            is_conn = bool(is_conn_attr)
        print("Connected:", is_conn)
        if not is_conn:
            raise RuntimeError("BLE connect failed")

        # try to request MTU=500 (best-effort)
        for method in ("request_mtu", "exchange_mtu", "request_mtu_size"):
            try:
                res = getattr(self.client, method, None)
                if callable(res):
                    maybe = res(500)
                    if asyncio.iscoroutine(maybe):
                        await maybe
                    print(f"Requested MTU via {method} (if supported).")
                    break
            except Exception:
                pass

        # start notify on data & control characteristics
        try:
            res = self.client.start_notify(DATA_CHAR_UUID, self.on_data_notify)
            if asyncio.iscoroutine(res):
                await res
        except Exception:
            await call_maybe_async(self.client, "start_notify", DATA_CHAR_UUID, self.on_data_notify)

        try:
            res = self.client.start_notify(CONTROL_CHAR_UUID, self.on_control_notify)
            if asyncio.iscoroutine(res):
                await res
        except Exception:
            try:
                await call_maybe_async(self.client, "start_notify", CONTROL_CHAR_UUID, self.on_control_notify)
            except Exception:
                # ignore if control notify not allowed
                pass

        # send START automatically
        await self._safe_write_control(b"START")
        print("Sent START command; streaming should begin shortly (if firmware accepted START).")

    async def _safe_write_control(self, payload: bytes):
        if not self.client:
            raise RuntimeError("Not connected")
        # try common signatures:
        try:
            res = self.client.write_gatt_char(CONTROL_CHAR_UUID, payload, response=True)
            if asyncio.iscoroutine(res):
                await res
            return
        except TypeError:
            try:
                res = self.client.write_gatt_char(CONTROL_CHAR_UUID, payload)
                if asyncio.iscoroutine(res):
                    await res
                return
            except Exception:
                pass
        except Exception:
            pass
        # fallback generic
        await call_maybe_async(self.client, "write_gatt_char", CONTROL_CHAR_UUID, payload)

    async def disconnect(self):
        # on shutdown, write remaining partial samples if any
        try:
            if self.sample_accum and self.last_recv_time:
                print(f"[SHUTDOWN] Writing leftover {len(self.sample_accum)} sample(s) to CSV")
                if self.csv_writer:
                    # Update statistics for leftover samples
                    for sample in self.sample_accum:
                        self._update_statistics(sample, self.last_recv_time)
                    # Write to CSV
                    self.csv_writer.write_batch(self.sample_accum, self.last_recv_time)
        except Exception as e:
            print("Error while writing leftovers:", e, file=sys.stderr)

        if self.client:
            # stop notifies (ignore errors)
            try:
                res = self.client.stop_notify(DATA_CHAR_UUID)
                if asyncio.iscoroutine(res):
                    await res
            except Exception:
                pass
            try:
                res = self.client.stop_notify(CONTROL_CHAR_UUID)
                if asyncio.iscoroutine(res):
                    await res
            except Exception:
                pass
            # try send STOP (best-effort)
            try:
                await self._safe_write_control(b"STOP")
            except Exception:
                pass
            try:
                await call_maybe_async(self.client, "disconnect")
            except Exception:
                pass
        if self.csv_writer:
            self.csv_writer.close()

# ---- main ----
async def main(args):
    if not args.outfile:
        print("Error: --outfile is required to save CSV. Use --outfile data.csv", file=sys.stderr)
        return 1

    client = NPGClient(device_address=args.device_address, name_prefix=args.device_name_prefix, csv_out=args.outfile, duration_minutes=args.duration)

    try:
        await client.connect_and_start()

        print(f"[CONFIG] Streaming will run for {client.duration_minutes} minute(s) after data starts")

        # Main loop - exit when disconnected or streaming duration expires
        while not client.disconnected:
            await asyncio.sleep(0.5)

            # Check if streaming duration has elapsed (only after streaming starts)
            if client.streaming_start_time is not None:
                elapsed = time.time() - client.streaming_start_time
                if elapsed >= client.duration_minutes * 60:  # Convert minutes to seconds
                    print(f"\n[INFO] Streaming duration of {client.duration_minutes} minute(s) completed")
                    break

        if client.disconnected:
            print("\n[INFO] Exiting due to BLE disconnect")

    except KeyboardInterrupt:
        print("\nInterrupted by user")
    except Exception as e:
        print("Error:", e, file=sys.stderr)
    finally:
        await client.disconnect()

        # Generate summary file
        if args.outfile:
            summary_path = args.outfile.rsplit(".", 1)[0] + "_summary.txt"
            client.write_summary(summary_path)

        print("Clean shutdown")
    return 0

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="NPG-Lite BLE Data Logger - Streams 3-channel biopotential data via Bluetooth LE",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  Basic usage (10 minutes):
    python record-log.py --outfile data.csv

  Custom duration (30 minutes):
    python record-log.py --outfile data.csv --duration 30

  With specific device address:
    python record-log.py --outfile data.csv --device-address AA:BB:CC:DD:EE:FF

  Custom device name and duration:
    python record-log.py --outfile data.csv --device-name-prefix MYNPG --duration 60
        """)
    parser.add_argument("--outfile", type=str, required=True, help="CSV file path to save recorded data (required)")
    parser.add_argument("--duration", type=int, default=DEFAULT_STREAMING_DURATION_MINUTES, 
                        help=f"Streaming duration in minutes (default: {DEFAULT_STREAMING_DURATION_MINUTES})")
    parser.add_argument("--device-address", type=str, default=None, 
                        help="Specific BLE device address to connect to (skips scanning)")
    parser.add_argument("--device-name-prefix", type=str, default="NPG", 
                        help="Device name prefix to scan for (default: NPG)")
    args = parser.parse_args()

    try:
        ret = asyncio.run(main(args))
        if isinstance(ret, int):
            sys.exit(ret)
    except Exception as exc:
        print("Fatal error:", exc, file=sys.stderr)
        raise
