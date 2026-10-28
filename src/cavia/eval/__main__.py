"""Run the reproducible CAVIA evaluation pipeline from JSONL session logs."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .aggregate import aggregate_trials, CONDITION_LABELS
from .figures import generate_figures
from .loader import load_sessions, session_metadata
from .questionnaires import load_and_score_questionnaires, TLX_ITEMS, SUS_ITEMS, CONTROL_ITEMS, CONFIDENCE_ITEMS
from .stats import run_statistics
from .trials import segment_trials, CONDITIONS


def _json_safe(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value) if math.isfinite(float(value)) else None
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if pd.isna(value):
        return None
    if isinstance(value, (str, int, bool)):
        return value
    return str(value)


def _descriptive(frame: pd.DataFrame, metric: str) -> dict[str, Any]:
    out = {}
    for condition in CONDITIONS:
        vals = []
        if metric in frame and "condition" in frame:
            vals = [float(v) for v in frame.loc[frame["condition"] == condition, metric]
                    if isinstance(v, (int, float, np.integer, np.floating)) and not pd.isna(v) and math.isfinite(float(v))]
        if vals:
            series = pd.Series(vals)
            out[condition] = {
                "n": len(vals), "mean": float(series.mean()),
                "sd": float(series.std(ddof=1)) if len(vals) > 1 else None,
                "median": float(series.median()),
                "q1": float(series.quantile(0.25)), "q3": float(series.quantile(0.75)),
                "iqr": float(series.quantile(0.75) - series.quantile(0.25)),
            }
        else:
            out[condition] = {"n": 0, "mean": None, "sd": None, "median": None, "q1": None, "q3": None, "iqr": None}
    return out


def _write_stats_markdown(stats: dict[str, Any], path: Path) -> None:
    lines = [
        "# CAVIA statistical analysis", "",
        "This report is generated from participant × condition summaries. It does not establish a hypothesis unless the required real study data exist.", "",
        "| Metric | Complete participants | Friedman χ² | p-value | Kendall's W |",
        "|---|---:|---:|---:|---:|",
    ]
    for key, item in stats.get("primary_metrics", {}).items():
        friedman = item.get("friedman") or {}
        lines.append(f"| {item.get('label', key)} | {item.get('n_complete', 0)} | "
                     f"{friedman.get('chi2', 'n/a')} | {friedman.get('p_value', 'n/a')} | {item.get('kendalls_w', 'n/a')} |")
        for pair in item.get("posthoc", []):
            lines.append(f"\n- **{key}: {pair.get('comparison', 'comparison')}** — raw p={pair.get('p_raw', 'n/a')}, Holm p={pair.get('p_holm', 'n/a')}, r={pair.get('effect_r', 'n/a')}.")
    lines += ["", "## Interpretation guardrails", "",
              "- H3 (incorrect selection) and H4 (perceived control) are reported descriptively as not-worse outcomes; a non-significant test is not evidence of equivalence.",
              "- Post-hoc planned comparisons are only run after a significant Friedman omnibus test.",
              "- Missing conditions or incomplete participant data are not imputed.",
              "- False EMG activations are not reported as a numerical result unless rest logs identify real device EMG events.",
              "- Agree statistical choices with the project guide before the study, as required by the evaluation brief.", ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def _quality_report(records, load_report, trials, rests, questionnaire_issues, generated_figures) -> dict[str, Any]:
    by_condition = {}
    for condition in sorted({r.get("condition", "UNKNOWN") for r in trials}):
        subset = [r for r in trials if r.get("condition") == condition]
        measured = [r for r in subset if not r.get("practice")]
        by_condition[condition] = {
            "all_trials": len(subset),
            "practice_trials_excluded": sum(bool(r.get("practice")) for r in subset),
            "no_lock": sum(r.get("status") == "no_lock" for r in measured),
            "no_confirm": sum(r.get("status") == "no_confirm" for r in measured),
            "aborted": sum(r.get("status") == "aborted" for r in measured),
            "technical_fault_trials": sum(bool(r.get("technical_fault")) for r in measured),
            "selection_times_over_60s_flagged": sum(bool(r.get("selection_time_flag")) for r in measured),
            "analysis_eligible_trials": sum(bool(r.get("analysis_eligible")) for r in measured),
        }
    device_rests = [r for r in rests if r.get("source_verified_device")]
    return {
        "input_validation": load_report,
        "records_used": len(records),
        "trial_count": len(trials),
        "rest_window_count": len(rests),
        "condition_counts": by_condition,
        "false_emg_activation_status": "measured_from_explicit_device_events" if device_rests else "not_applicable_keyboard_or_source_unverified",
        "device_verified_rest_windows": len(device_rests),
        "questionnaire_issues": questionnaire_issues,
        "figures_generated": generated_figures,
        "privacy_note": "Participant identifiers are treated as anonymous IDs; inspect input logs to ensure they contain no names.",
    }


def _write_exclusions(trials: list[dict[str, Any]], path: Path) -> None:
    rows = []
    for row in trials:
        reasons = []
        if row.get("practice"):
            reasons.append("practice trial")
        if row.get("status") != "valid":
            reasons.append(f"status={row.get('status')}")
        if row.get("technical_fault"):
            reasons.append("experimenter-noted technical fault")
        if reasons:
            rows.append({
                "participant": row.get("participant"), "condition": row.get("condition"),
                "session": row.get("session"), "trial": row.get("trial"),
                "status": row.get("status"), "practice": row.get("practice"),
                "technical_fault": row.get("technical_fault"),
                "technical_fault_reason": row.get("technical_fault_reason"),
                "selection_time_flag": row.get("selection_time_flag"),
                "exclusion_reason": "; ".join(reasons),
            })
    pd.DataFrame(rows, columns=[
        "participant", "condition", "session", "trial", "status", "practice", "technical_fault",
        "technical_fault_reason", "selection_time_flag", "exclusion_reason"
    ]).to_csv(path, index=False)




def _write_descriptives(trials: pd.DataFrame, aggregate: pd.DataFrame, out: Path) -> None:
    # Interaction metrics describe eligible measured trials; questionnaire scores are one value per participant × condition.
    groups = {
        "Commands and time": [
            ("commands", "trials", "commands", "trial"),
            ("selection_time_s", "trials", "selection_time_s", "trial"),
            ("task_time_s", "trials", "task_time_s", "trial"),
            ("t_lock_s", "trials", "t_lock_s", "trial"),
        ],
        "Errors and acceptance": [
            ("incorrect_rate", "trials", "incorrect", "trial_rate"),
            ("corrected_rate", "trials", "corrected", "trial_rate"),
            ("first_option_acceptance_rate", "trials", "first_option_accepted", "trial_rate"),
            ("target_in_first_option_rate", "trials", "target_rank", "rank_one_rate"),
        ],
        "Menu and grasp": [
            ("full_menu_rate", "trials", "from_full_menu", "trial_rate"),
            ("override_rate", "trials", "override", "trial_rate"),
            ("incompatible_choice_rate", "trials", "compatible", "incompatible_rate"),
            ("grasp_success_rate", "trials", "grasp_success", "trial_rate"),
            ("target_suggestion_hit_rate", "trials", "target_in_menu", "trial_rate"),
        ],
        "Questionnaires": [
            ("raw_tlx", "aggregate", "raw_tlx", "participant"),
            ("sus_score", "aggregate", "sus_score", "participant"),
            ("control_score", "aggregate", "control_score", "participant"),
            ("confidence_score", "aggregate", "confidence_score", "participant"),
        ],
    }
    rows = []
    for category, specs in groups.items():
        for metric, source_name, source_metric, value_type in specs:
            source = trials if source_name == "trials" else aggregate
            for condition in CONDITIONS:
                subset = source[source["condition"] == condition] if not source.empty and "condition" in source else pd.DataFrame()
                if source_name == "trials" and not subset.empty and "analysis_eligible" in subset:
                    subset = subset[subset["analysis_eligible"].fillna(False)]
                vals = []
                if not subset.empty and source_metric in subset:
                    for value in subset[source_metric]:
                        if value_type == "rank_one_rate":
                            if isinstance(value, (int, float, np.integer, np.floating)) and not pd.isna(value):
                                vals.append(1.0 if float(value) == 1 else 0.0)
                        elif value_type == "incompatible_rate":
                            if isinstance(value, (bool, np.bool_)):
                                vals.append(0.0 if bool(value) else 1.0)
                        elif value_type == "trial_rate":
                            if isinstance(value, (bool, np.bool_)):
                                vals.append(float(value))
                        elif isinstance(value, (int, float, np.integer, np.floating)) and not pd.isna(value) and math.isfinite(float(value)):
                            vals.append(float(value))
                series = pd.Series(vals)
                rows.append({
                    "category": category, "metric": metric, "condition": condition,
                    "observation_unit": "trial" if source_name == "trials" else "participant_condition",
                    "n": len(vals),
                    "mean": float(series.mean()) if len(vals) else None,
                    "sd": float(series.std(ddof=1)) if len(vals) > 1 else None,
                    "median": float(series.median()) if len(vals) else None,
                    "q1": float(series.quantile(0.25)) if len(vals) else None,
                    "q3": float(series.quantile(0.75)) if len(vals) else None,
                    "iqr": float(series.quantile(0.75) - series.quantile(0.25)) if len(vals) else None,
                })
    pd.DataFrame(rows).to_csv(out / "descriptive_stats.csv", index=False)
    lines = [
        "# Descriptive statistics by condition", "",
        "Interaction metrics summarize eligible measured trials; questionnaire scores summarize participant × condition responses. `n` is the number of non-missing observations at the level shown. These descriptive trial-level spreads do not replace participant-level repeated-measures tests. Empty cells mean no eligible data, not zero.", "",
    ]
    for category in groups:
        lines.extend([f"## {category}", "", "| Metric | Condition | Observation unit | n | Mean ± SD | Median (IQR) |", "|---|---|---|---:|---:|---:|"])
        for row in rows:
            if row["category"] != category:
                continue
            mean_sd = "n/a" if row["mean"] is None else f"{row['mean']:.3f} ± {row['sd']:.3f}" if row["sd"] is not None else f"{row['mean']:.3f} ± n/a"
            median_iqr = "n/a" if row["median"] is None else f"{row['median']:.3f} ({row['iqr']:.3f})"
            lines.append(f"| {row['metric']} | {row['condition']} | {row['observation_unit']} | {row['n']} | {mean_sd} | {median_iqr} |")
        lines.append("")
    (out / "descriptive_stats.md").write_text("\n".join(lines), encoding="utf-8")


def _write_results_json(aggregate: pd.DataFrame, trials: pd.DataFrame, stats: dict, quality: dict, figures: list[str], out: Path) -> None:
    condition_data = {}
    metric_map = {
        "commands": "commands_mean", "selection_time_s": "selection_time_s_mean",
        "task_time_s": "task_time_s_mean", "t_lock_s": "t_lock_s_mean",
        "incorrect_rate": "incorrect_rate", "first_option_acceptance_rate": "first_option_acceptance_rate",
        "grasp_success_rate": "grasp_success_rate", "full_menu_rate": "full_menu_rate",
        "override_rate": "override_rate", "raw_tlx": "raw_tlx", "sus_score": "sus_score",
        "control_score": "control_score", "confidence_score": "confidence_score",
    }
    for condition in CONDITIONS:
        row = {"label": CONDITION_LABELS.get(condition, condition), "available": False, "metrics": {}}
        if not aggregate.empty:
            group = aggregate[aggregate["condition"] == condition]
            if not group.empty:
                row["available"] = True
                row["participants_n"] = int(group["participant"].nunique())
                for public_metric, source_metric in metric_map.items():
                    row["metrics"][public_metric] = _descriptive(group, source_metric)[condition]
        condition_data[condition] = row
    payload = {
        "schema_version": 1,
        "research_question": "Can preference-ranked, confidence-adaptive grip menus reduce EMG command burden and selection time without increasing incorrect choices or reducing perceived user control?",
        "data_available": bool(not trials.empty and trials.get("analysis_eligible", pd.Series(dtype=bool)).fillna(False).any()),
        "conditions": condition_data,
        "statistics": stats,
        "quality": quality,
        "figures": [{"id": name, "png": f"figures/{name}.png", "svg": f"figures/{name}.svg"} for name in figures],
        "caveats": [
            "The current runtime supports C3_ADAPTIVE only; no C1/C2 comparison is possible until those conditions are implemented and measured.",
            "Keyboard-emulator rest activity is not a meaningful false-EMG-activation result; the metric remains not applicable without verified device events.",
            "Synthetic test logs verify calculations only and are not research observations.",
        ],
    }
    (out / "results.json").write_text(json.dumps(_json_safe(payload), indent=2, allow_nan=False), encoding="utf-8")


def run(input_path: str | Path, out_dir: str | Path, questionnaires_path: str | Path | None = None, time_cap_s: float = 60.0) -> dict[str, Any]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    records, load_report = load_sessions(input_path)
    metadata = session_metadata(records)
    trials, rests = segment_trials(records, metadata, time_cap_s=time_cap_s)

    questionnaire_issues: list[str] = []
    scored_q = pd.DataFrame()
    if questionnaires_path is not None:
        scored_q, questionnaire_issues = load_and_score_questionnaires(questionnaires_path)
        scored_q.to_csv(out / "questionnaires_scored.csv", index=False)
    else:
        columns = ["participant", "condition", *TLX_ITEMS, *SUS_ITEMS, *CONTROL_ITEMS, *CONFIDENCE_ITEMS,
                   "raw_tlx", "sus_score", "control_score", "confidence_score", "questionnaire_issues"]
        pd.DataFrame(columns=columns).to_csv(out / "questionnaires_scored.csv", index=False)

    trial_frame = pd.DataFrame(trials)
    if trial_frame.empty:
        trial_frame = pd.DataFrame(columns=[
            "session", "participant", "condition", "order_position", "trial", "task_id", "object", "region",
            "target_grip", "practice", "status", "t_lock_s", "selection_time_s", "task_time_s", "commands",
            "nav_commands", "full_opens", "backs", "confirm_commands", "policy", "menu_len", "confidence_vision",
            "region_evidence_n", "target_in_menu", "target_rank", "confirmed_grip", "final_grip", "incorrect",
            "corrected", "first_option_accepted", "from_full_menu", "override", "compatible", "selection_status",
            "grasp_success", "technical_fault", "technical_fault_reason", "analysis_eligible", "selection_time_flag",
            "emg_source",
        ])
    trial_frame.to_csv(out / "trials.csv", index=False)
    rest_frame = pd.DataFrame(rests)
    if rest_frame.empty:
        rest_frame = pd.DataFrame(columns=["session", "participant", "condition", "rest", "duration_s", "device_gestures",
                                           "false_activations_per_min", "source_verified_device", "incomplete"])
    rest_frame.to_csv(out / "rest_windows.csv", index=False)

    aggregate = aggregate_trials(trials, scored_q if not scored_q.empty else None)
    if aggregate.empty:
        aggregate = pd.DataFrame(columns=[
            "participant", "condition", "condition_label", "order_position", "trials_total", "valid_trials",
            "no_lock_trials", "no_confirm_trials", "aborted_trials", "practice_trials_excluded",
            "technical_fault_trials_excluded", "analysis_trials", "selection_time_over_cap_flags",
            "commands_mean", "commands_median", "selection_time_s_mean", "selection_time_s_median",
            "task_time_s_mean", "task_time_s_median", "t_lock_s_mean", "t_lock_s_median",
            "menu_len_mean", "menu_len_median", "incorrect_rate", "corrected_rate",
            "first_option_acceptance_rate", "target_in_first_option_rate", "full_menu_rate", "override_rate",
            "incompatible_choice_rate", "grasp_success_rate", "cancellations", "target_suggestion_hit_rate",
        ])
    aggregate.to_csv(out / "participant_condition.csv", index=False)
    _write_descriptives(trial_frame, aggregate, out)
    stats = run_statistics(aggregate)
    (out / "stats.json").write_text(json.dumps(_json_safe(stats), indent=2, allow_nan=False), encoding="utf-8")
    _write_stats_markdown(stats, out / "stats.md")

    figures_dir = out / "figures"
    figures = generate_figures(trial_frame, aggregate, figures_dir)
    quality = _quality_report(records, load_report, trials, rests, questionnaire_issues, figures)
    (out / "quality_report.json").write_text(json.dumps(_json_safe(quality), indent=2, allow_nan=False), encoding="utf-8")
    _write_exclusions(trials, out / "exclusions.csv")
    _write_results_json(aggregate, trial_frame, stats, quality, figures, out)
    return {"out_dir": str(out), "records": len(records), "trials": len(trials), "rest_windows": len(rests),
            "figures": figures, "quality": quality, "stats": stats}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("logs", type=Path, help="JSONL session log file or directory (read-only)")
    parser.add_argument("--out", type=Path, default=Path("data/results/"), help="output directory (default: data/results/)")
    parser.add_argument("--questionnaires", type=Path, help="optional questionnaires.csv")
    parser.add_argument("--time-cap", type=float, default=60.0, help="flag selection times above this cap; do not remove them")
    args = parser.parse_args(argv)
    if args.time_cap <= 0:
        parser.error("--time-cap must be positive")
    try:
        summary = run(args.logs, args.out, args.questionnaires, args.time_cap)
    except (OSError, ValueError) as exc:
        parser.exit(2, f"Evaluation failed: {exc}\n")
    print(f"Evaluation complete: {summary['records']} records, {summary['trials']} trials, {summary['rest_windows']} rest windows.")
    print(f"Outputs: {summary['out_dir']}")
    print(f"Figures generated: {', '.join(summary['figures'])}")
    if summary["quality"]["false_emg_activation_status"] != "measured_from_explicit_device_events":
        print("False EMG activations: not applicable (no verified real-device events in rest windows).")
    if summary["quality"]["input_validation"]["warnings"]:
        print(f"Input warnings: {len(summary['quality']['input_validation']['warnings'])}; see quality_report.json.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())