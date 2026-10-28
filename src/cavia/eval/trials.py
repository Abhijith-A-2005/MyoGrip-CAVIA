"""Trial segmentation and all per-trial metrics defined in the CAVIA evaluation brief."""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

CONDITIONS = ["C1_MANUAL", "C2_STATIC", "C3_ADAPTIVE"]
GESTURE_KEYS = {"w", "s", "a", "d", "e"}
TECHNICAL_FAULT = re.compile(r"\b(technical fault|camera dropout|camera failure|crash|system failure|runtime failure|device fault)\b", re.I)


def _data(record: dict[str, Any]) -> dict[str, Any]:
    value = record.get("data", {})
    return value if isinstance(value, dict) else {}


def _menu_payload(record: dict[str, Any]) -> dict[str, Any]:
    """Accept the documented flat menu event and current runtime's nested decision event."""
    data = _data(record)
    decision = data.get("decision")
    if isinstance(decision, dict):
        proposal = decision.get("proposal")
        if isinstance(proposal, dict):
            merged = dict(proposal)
            for key in ("compatible", "ranking_source", "region_evidence_n", "reason", "requested_region", "user"):
                if key in decision and key not in merged:
                    merged[key] = decision[key]
            return merged
        return decision
    return data


def _menu_id(payload: dict[str, Any]) -> Any:
    return payload.get("menu_id", payload.get("id"))


def _selection_payload(record: dict[str, Any]) -> dict[str, Any]:
    data = _data(record)
    selection = data.get("selection")
    return selection if isinstance(selection, dict) else data


def _is_aborted(records: list[dict[str, Any]]) -> bool:
    for record in records:
        data = _data(record)
        if record.get("type") == "note":
            message = str(data.get("message", ""))
            if re.search(r"\b(abort(?:ed)?|technical fault|camera dropout|crash|system failure)\b", message, re.I):
                return True
        if record.get("type") in {"trial_abort", "aborted"}:
            return True
        if record.get("type") == "trial_end" and data.get("aborted") is True:
            return True
    return False


def _has_technical_fault(records: list[dict[str, Any]]) -> tuple[bool, str]:
    reasons = []
    for record in records:
        if record.get("type") == "note":
            message = str(_data(record).get("message", ""))
            if TECHNICAL_FAULT.search(message):
                reasons.append(message.strip()[:200])
        end_notes = _data(record).get("notes")
        if end_notes and TECHNICAL_FAULT.search(str(end_notes)):
            reasons.append(str(end_notes).strip()[:200])
    return bool(reasons), "; ".join(dict.fromkeys(reasons))


def _as_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "yes", "1"}:
            return True
        if normalized in {"false", "no", "0"}:
            return False
    return None


def segment_trials(records: list[dict[str, Any]], metadata: dict[str, dict[str, Any]], time_cap_s: float = 60.0) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return all trial rows and rest-window rows. Source records are never changed."""
    by_session: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        session = str(record.get("session") or record.get("_source_file") or "unknown")
        by_session[session].append(record)
    trials: list[dict[str, Any]] = []
    rests: list[dict[str, Any]] = []

    for session, session_records in by_session.items():
        session_records.sort(key=lambda r: (r["ts"], r.get("_line", 0)))
        meta = metadata.get(session, {})
        participant = str(meta.get("participant") or "unknown")
        condition = str(meta.get("condition") or "UNKNOWN")
        active: dict[str, Any] | None = None
        completed: list[dict[str, Any]] = []

        def finish_trial(end_record: dict[str, Any] | None, forced_aborted: bool = False) -> None:
            nonlocal active
            if active is None:
                return
            tr_records = active["records"]
            start_record = active["start"]
            start_data = _data(start_record)
            end_data = _data(end_record) if end_record else {}
            t_start = start_record["ts"]
            t_end = end_record["ts"] if end_record else None
            end_ts = float(t_end) if t_end is not None else None
            in_trial = [r for r in tr_records if r["ts"] >= t_start and (end_ts is None or r["ts"] <= end_ts)]
            menus = []
            confirmations = []
            for r in in_trial:
                if r.get("type") == "menu":
                    payload = _menu_payload(r)
                    menus.append((r, payload))
                elif r.get("type") == "confirmed":
                    confirmations.append(r)
            first_menu = next(((r, p) for r, p in menus if r["ts"] >= t_start), None)
            first_confirm = next((r for r in confirmations if first_menu and r["ts"] >= first_menu[0]["ts"]), None)
            locked = next((r for r in in_trial if r.get("type") == "vision" and str(_data(r).get("state", "")).upper() == "LOCKED" and r["ts"] >= t_start), None)

            if forced_aborted or _is_aborted(in_trial) or end_record is None:
                status = "aborted"
            elif first_confirm is not None and first_menu is not None:
                status = "valid"
            elif locked is None:
                status = "no_lock"
            else:
                status = "no_confirm"

            t_menu = first_menu[0]["ts"] if first_menu else None
            t_confirm = first_confirm["ts"] if first_confirm else None
            selection_time = max(0.0, t_confirm - t_menu) if t_menu is not None and t_confirm is not None else None
            task_time = max(0.0, end_ts - t_start) if end_ts is not None else None
            lock_time = max(0.0, locked["ts"] - t_start) if locked else None

            confirm_data = _data(first_confirm) if first_confirm else {}
            first_menu_id = confirm_data.get("menu_id")
            confirmed_menu = None
            if first_confirm:
                for menu_record, payload in menus:
                    if _menu_id(payload) == first_menu_id:
                        confirmed_menu = (menu_record, payload)
                        break
            menu_payload = confirmed_menu[1] if confirmed_menu else {}
            items = menu_payload.get("items") if isinstance(menu_payload.get("items"), list) else []
            items = [str(x).upper() for x in items]
            policy = menu_payload.get("policy")
            confidence = menu_payload.get("confidence") if isinstance(menu_payload.get("confidence"), dict) else {}
            context = menu_payload.get("context") if isinstance(menu_payload.get("context"), dict) else {}

            keydowns = []
            if t_menu is not None and t_confirm is not None:
                keydowns = [
                    r for r in in_trial
                    if r.get("type") == "key_down"
                    and t_menu < r["ts"] <= t_confirm
                    and str(_data(r).get("key", "")).lower() in GESTURE_KEYS
                ]
            keys = [str(_data(r).get("key", "")).lower() for r in keydowns]
            commands = len(keys) if status == "valid" else None
            nav_commands = sum(k in {"w", "s"} for k in keys) if status == "valid" else None
            full_opens = sum(k == "d" for k in keys) if status == "valid" else None
            backs = sum(k == "e" for k in keys) if status == "valid" else None
            confirms = sum(k == "a" for k in keys) if status == "valid" else None

            target = start_data.get("target_grip")
            target = str(target).upper() if target not in (None, "") else None
            first_grip = str(confirm_data.get("grip")).upper() if confirm_data.get("grip") not in (None, "") else None
            all_confirms = [r for r in confirmations if first_menu and r["ts"] >= first_menu[0]["ts"]]
            final_data = _data(all_confirms[-1]) if all_confirms else {}
            final_grip = str(final_data.get("grip")).upper() if final_data.get("grip") not in (None, "") else first_grip
            used_back_to_reselect = False
            if len(all_confirms) > 1:
                first_confirmation_ts = all_confirms[0]["ts"]
                next_confirmation_ts = all_confirms[1]["ts"]
                used_back_to_reselect = any(
                    r.get("type") == "key_down"
                    and str(_data(r).get("key", "")).lower() == "e"
                    and first_confirmation_ts < r["ts"] < next_confirmation_ts
                    for r in in_trial
                )
            corrected = (len(all_confirms) > 1 and used_back_to_reselect and target is not None
                         and first_grip != target)
            incorrect = (first_grip != target) if target is not None and status == "valid" else None

            navigation_before_confirm = any(k in {"w", "s", "d"} for k in keys)
            first_option_accepted = (
                first_grip == items[0] and not navigation_before_confirm
                if status == "valid" and first_grip is not None and items else None
            )
            target_in_menu = target in items if target is not None and confirmed_menu else None
            target_rank = items.index(target) + 1 if target is not None and target in items and confirmed_menu else None

            selection_updates = []
            for r in in_trial:
                if r.get("type") == "preference_update":
                    selection_updates.append((r, _selection_payload(r)))
            matching_update = None
            if selection_updates:
                # Prefer an update whose interaction ID matches the first confirmation; otherwise match grip.
                interaction_id = confirm_data.get("interaction_id")
                matching_update = next(
                    (s for r, s in selection_updates if interaction_id and _data(r).get("interaction_id") == interaction_id),
                    None,
                )
                if matching_update is None:
                    matching_update = next((s for _, s in selection_updates if str(s.get("grip", "")).upper() == (first_grip or "")), selection_updates[0][1])
            from_full_menu = _as_bool(matching_update.get("from_full_menu")) if matching_update else None
            compatible = _as_bool(matching_update.get("compatible")) if matching_update else None
            selection_status = matching_update.get("status") if matching_update else None
            override = (first_grip not in items) if first_grip is not None and confirmed_menu else None
            grasp_success = _as_bool(end_data.get("grasp_success")) if end_record else None
            technical_fault, fault_reason = _has_technical_fault(in_trial)
            practice = bool(start_data.get("practice", False))
            analysis_eligible = status == "valid" and not practice and not technical_fault
            if selection_time is not None and selection_time > time_cap_s:
                time_flag = f"over_{time_cap_s:g}s"
            else:
                time_flag = None

            row = {
                "session": session, "participant": participant, "condition": condition,
                "order_position": None, "trial": start_data.get("trial", start_record.get("trial")),
                "task_id": start_data.get("task_id"), "object": start_data.get("object") or context.get("object"),
                "region": start_data.get("region") or context.get("region"), "target_grip": target,
                "practice": practice, "status": status,
                "t_lock_s": lock_time, "selection_time_s": selection_time, "task_time_s": task_time,
                "commands": commands, "nav_commands": nav_commands, "full_opens": full_opens, "backs": backs,
                "confirm_commands": confirms, "policy": policy, "menu_len": len(items) if confirmed_menu else None,
                "confidence_vision": confidence.get("vision"), "region_evidence_n": menu_payload.get("region_evidence_n", confidence.get("evidence_n")),
                "target_in_menu": target_in_menu, "target_rank": target_rank,
                "confirmed_grip": first_grip, "final_grip": final_grip,
                "incorrect": incorrect, "corrected": bool(corrected),
                "first_option_accepted": first_option_accepted, "from_full_menu": from_full_menu,
                "override": override, "compatible": compatible, "selection_status": selection_status,
                "grasp_success": grasp_success, "technical_fault": technical_fault, "technical_fault_reason": fault_reason,
                "analysis_eligible": analysis_eligible, "selection_time_flag": time_flag,
                "emg_source": None,
            }
            trials.append(row)
            active = None

        for record in session_records:
            kind = record.get("type")
            data = _data(record)
            if kind == "trial_start":
                if active is not None:
                    finish_trial(None, forced_aborted=True)
                active = {"start": record, "records": [record]}
            elif active is not None:
                active["records"].append(record)
                if kind == "trial_end":
                    finish_trial(record)
            # record rest windows separately; pair start/end by rest number
        if active is not None:
            finish_trial(None, forced_aborted=True)

        # Rest-window parsing: source logs remain untouched.
        active_rests: dict[str, dict[str, Any]] = {}
        for record in session_records:
            kind = record.get("type")
            data = _data(record)
            rest_id = data.get("rest", record.get("rest"))
            if kind == "rest_start":
                key = str(rest_id if rest_id is not None else f"start-{record['ts']}")
                active_rests[key] = {"start": record, "records": [record]}
            elif active_rests:
                for item in active_rests.values():
                    if record["ts"] >= item["start"]["ts"]:
                        item["records"].append(record)
            if kind == "rest_end":
                key = str(rest_id if rest_id is not None else f"start-{record['ts']}")
                item = active_rests.pop(key, None)
                if item is None and active_rests:
                    key, item = next(iter(active_rests.items()))
                    active_rests.pop(key, None)
                if item:
                    start = item["start"]
                    duration = data.get("duration_s")
                    if not isinstance(duration, (int, float)) or duration <= 0:
                        duration = record["ts"] - start["ts"]
                    rest_records = item["records"] + [record]
                    device_gestures = [
                        r for r in rest_records
                        if r.get("type") in {"emg", "key_down"}
                        and (_data(r).get("source") == "device" or r.get("emg_source") == "device")
                        and (_data(r).get("event") in {"SF", "SE", "LF", "LE", "HE"} or str(_data(r).get("key", "")).lower() in GESTURE_KEYS)
                    ]
                    source_verified = any(
                        _data(r).get("source") == "device" or r.get("emg_source") == "device"
                        for r in rest_records
                    )
                    rests.append({
                        "session": session, "participant": participant, "condition": condition,
                        "rest": rest_id, "duration_s": float(duration),
                        "device_gestures": len(device_gestures) if source_verified else None,
                        "false_activations_per_min": len(device_gestures) / float(duration) * 60 if duration and source_verified else None,
                        "source_verified_device": source_verified,
                    })
        # Unclosed rest windows are quality-report entries, not false activation measurements.
        for key, item in active_rests.items():
            rests.append({"session": session, "participant": participant, "condition": condition,
                          "rest": key, "duration_s": None, "device_gestures": None,
                          "false_activations_per_min": None, "source_verified_device": False, "incomplete": True})

    # Assign condition order per participant based on first occurrence in the session logs.
    order_keys = {}
    for row in trials:
        key = (row["participant"], row["condition"])
        prior = order_keys.get(key)
        session_order = min((r["ts"] for r in records if str(r.get("session") or r.get("_source_file") or "unknown") == row["session"]), default=0)
        if prior is None or session_order < prior:
            order_keys[key] = session_order
    for participant in sorted({r["participant"] for r in trials}):
        ordered = sorted(((ts, cond) for (p, cond), ts in order_keys.items() if p == participant), key=lambda x: x[0])
        positions = {cond: i + 1 for i, (_, cond) in enumerate(ordered)}
        for row in trials:
            if row["participant"] == participant:
                row["order_position"] = positions.get(row["condition"])
    return trials, rests