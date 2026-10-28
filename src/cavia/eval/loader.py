"""Read-only loading and validation for CAVIA session JSONL logs."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _candidate_files(path: str | Path) -> list[Path]:
    source = Path(path)
    if source.is_file():
        return [source] if source.suffix.lower() in {".jsonl", ".ndjson"} else []
    if source.is_dir():
        return sorted(p for p in source.rglob("*") if p.is_file() and p.suffix.lower() in {".jsonl", ".ndjson"})
    raise FileNotFoundError(f"Input path does not exist: {source}")


def load_sessions(path: str | Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Load records without modifying source files; malformed lines are counted and skipped."""
    files = _candidate_files(path)
    if not files:
        raise FileNotFoundError(f"No .jsonl/.ndjson session logs found at: {path}")
    records: list[dict[str, Any]] = []
    report: dict[str, Any] = {
        "input_path": str(path),
        "files_found": len(files),
        "files_read": 0,
        "lines_read": 0,
        "records_loaded": 0,
        "malformed_json_lines": 0,
        "invalid_records": 0,
        "warnings": [],
        "files": [],
    }
    for file in files:
        file_report = {"file": str(file), "lines": 0, "loaded": 0, "malformed": 0, "invalid": 0}
        try:
            with file.open("r", encoding="utf-8") as stream:
                for line_number, raw in enumerate(stream, 1):
                    if not raw.strip():
                        continue
                    file_report["lines"] += 1
                    report["lines_read"] += 1
                    try:
                        record = json.loads(raw)
                    except json.JSONDecodeError as exc:
                        report["malformed_json_lines"] += 1
                        file_report["malformed"] += 1
                        report["warnings"].append(f"{file}:{line_number}: malformed JSON ({exc.msg})")
                        continue
                    if not isinstance(record, dict) or not isinstance(record.get("type"), str):
                        report["invalid_records"] += 1
                        file_report["invalid"] += 1
                        report["warnings"].append(f"{file}:{line_number}: record must be an object with string 'type'")
                        continue
                    try:
                        ts = float(record["ts"])
                        if not (ts == ts and abs(ts) != float("inf")):
                            raise ValueError
                    except (KeyError, TypeError, ValueError):
                        report["invalid_records"] += 1
                        file_report["invalid"] += 1
                        report["warnings"].append(f"{file}:{line_number}: missing or invalid monotonic 'ts'")
                        continue
                    data = record.get("data", {})
                    if not isinstance(data, dict):
                        report["invalid_records"] += 1
                        file_report["invalid"] += 1
                        report["warnings"].append(f"{file}:{line_number}: 'data' must be an object")
                        continue
                    rec = dict(record)
                    rec["ts"] = ts
                    rec["data"] = data
                    rec["_source_file"] = str(file)
                    rec["_line"] = line_number
                    rec.setdefault("session", file.stem)
                    rec.setdefault("user", data.get("participant", data.get("user")))
                    rec.setdefault("condition", data.get("condition"))
                    records.append(rec)
                    file_report["loaded"] += 1
                    report["records_loaded"] += 1
        except OSError as exc:
            report["warnings"].append(f"{file}: could not read file ({exc})")
            continue
        report["files_read"] += 1
        report["files"].append(file_report)
    records.sort(key=lambda r: (str(r.get("session") or ""), r["ts"], r["_line"]))
    return records, report


def session_metadata(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Resolve participant and condition per session from record fields and session_start events."""
    result: dict[str, dict[str, Any]] = {}
    for rec in records:
        session = str(rec.get("session") or Path(rec["_source_file"]).stem)
        meta = result.setdefault(session, {"participant": None, "condition": None, "first_ts": rec["ts"], "source_file": rec["_source_file"]})
        data = rec["data"]
        if rec.get("user") not in (None, "") and meta["participant"] is None:
            meta["participant"] = str(rec["user"])
        if rec["type"] == "session_start" and data.get("participant") not in (None, ""):
            meta["participant"] = str(data["participant"])
        elif data.get("participant") and meta["participant"] is None:
            meta["participant"] = str(data["participant"])
        if rec.get("condition") not in (None, ""):
            meta["condition"] = str(rec["condition"])
        if data.get("condition") not in (None, "") and rec["type"] == "session_start":
            meta["condition"] = str(data["condition"])
        meta["first_ts"] = min(meta["first_ts"], rec["ts"])
    for meta in result.values():
        meta["participant"] = meta["participant"] or "unknown"
        meta["condition"] = meta["condition"] or "UNKNOWN"
    return result