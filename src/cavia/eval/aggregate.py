"""Participant × condition summaries; all values are derived from trial/questionnaire rows."""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

import pandas as pd

METRICS = [
    "commands", "selection_time_s", "task_time_s", "t_lock_s", "incorrect_rate",
    "corrected_rate", "first_option_acceptance_rate", "target_in_first_option_rate",
    "full_menu_rate", "override_rate", "incompatible_choice_rate", "grasp_success_rate",
    "cancellations", "menu_len_mean",
]
CONDITION_LABELS = {
    "C1_MANUAL": "Manual",
    "C2_STATIC": "Static",
    "C3_ADAPTIVE": "Adaptive",
}


def _mean(values: list[Any]) -> float | None:
    numeric = [float(v) for v in values if isinstance(v, (int, float)) and not pd.isna(v)]
    return sum(numeric) / len(numeric) if numeric else None


def _rate(values: list[Any]) -> float | None:
    numeric = [v for v in values if isinstance(v, bool)]
    return sum(numeric) / len(numeric) if numeric else None


def aggregate_trials(trials: list[dict[str, Any]], questionnaires: pd.DataFrame | None = None) -> pd.DataFrame:
    """Summarize non-practice trials by participant and condition.

    Invalid trials remain represented through status counts; outcome metrics use valid,
    non-practice trials without experimenter-noted technical faults.
    """
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in trials:
        if not row.get("practice", False):
            grouped[(str(row.get("participant", "unknown")), str(row.get("condition", "UNKNOWN")))].append(row)
    rows = []
    for (participant, condition), all_rows in sorted(grouped.items()):
        eligible = [r for r in all_rows if r.get("analysis_eligible")]
        row: dict[str, Any] = {
            "participant": participant, "condition": condition,
            "condition_label": CONDITION_LABELS.get(condition, condition),
            "order_position": next((r.get("order_position") for r in all_rows if r.get("order_position") is not None), None),
            "trials_total": len(all_rows),
            "valid_trials": sum(r.get("status") == "valid" for r in all_rows),
            "no_lock_trials": sum(r.get("status") == "no_lock" for r in all_rows),
            "no_confirm_trials": sum(r.get("status") == "no_confirm" for r in all_rows),
            "aborted_trials": sum(r.get("status") == "aborted" for r in all_rows),
            "practice_trials_excluded": sum(bool(r.get("practice")) for r in trials if r.get("participant") == participant and r.get("condition") == condition),
            "technical_fault_trials_excluded": sum(bool(r.get("technical_fault")) for r in all_rows),
            "analysis_trials": len(eligible),
            "selection_time_over_cap_flags": sum(bool(r.get("selection_time_flag")) for r in eligible),
        }
        for metric in ("commands", "selection_time_s", "task_time_s", "t_lock_s", "menu_len"):
            row[metric + "_mean"] = _mean([r.get(metric) for r in eligible])
            row[metric + "_median"] = float(pd.Series([r.get(metric) for r in eligible if isinstance(r.get(metric), (int, float))]).median()) if any(isinstance(r.get(metric), (int, float)) and not pd.isna(r.get(metric)) for r in eligible) else None
        row["incorrect_rate"] = _rate([r.get("incorrect") for r in eligible])
        row["corrected_rate"] = _rate([r.get("corrected") for r in eligible])
        row["first_option_acceptance_rate"] = _rate([r.get("first_option_accepted") for r in eligible])
        row["target_in_first_option_rate"] = _rate([
            (r.get("target_rank") == 1) if r.get("target_rank") is not None else None for r in eligible
        ])
        row["full_menu_rate"] = _rate([r.get("from_full_menu") for r in eligible])
        row["override_rate"] = _rate([r.get("override") for r in eligible])
        row["incompatible_choice_rate"] = _rate([False if r.get("compatible") is None else not r.get("compatible") for r in eligible if r.get("compatible") is not None])
        row["grasp_success_rate"] = _rate([r.get("grasp_success") for r in eligible])
        row["cancellations"] = sum(str(r.get("selection_status", "")).lower() == "cancelled" for r in all_rows)
        policy_counts = defaultdict(int)
        for trial in eligible:
            if trial.get("policy"):
                policy_counts[str(trial["policy"])] += 1
        for policy in ("ONE_CONFIRM", "TOP_TWO", "FULL_COMPATIBLE", "FULL_MENU"):
            row[f"policy_{policy.lower()}_count"] = policy_counts[policy]
        row["target_suggestion_hit_rate"] = _rate([r.get("target_in_menu") for r in eligible])
        rows.append(row)
    frame = pd.DataFrame(rows)
    if questionnaires is not None and not questionnaires.empty:
        score_columns = [c for c in ("raw_tlx", "sus_score", "control_score", "confidence_score") if c in questionnaires.columns]
        qcols = ["participant", "condition"] + score_columns
        frame = frame.merge(questionnaires[qcols], on=["participant", "condition"], how="left", validate="one_to_one")
    return frame