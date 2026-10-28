"""Repeated-measures statistics for the small-n within-subjects design."""
from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import friedmanchisquare, norm, wilcoxon
from statsmodels.stats.multitest import multipletests

CONDITIONS = ["C1_MANUAL", "C2_STATIC", "C3_ADAPTIVE"]
PRIMARY_METRICS = {
    "commands_mean": "EMG commands per selection",
    "selection_time_s_mean": "Grip selection time (s)",
    "incorrect_rate": "Incorrect selection rate",
    "control_score": "Perceived control score",
}
PLANNED_PAIRS = [("C2_STATIC", "C1_MANUAL"), ("C3_ADAPTIVE", "C2_STATIC")]


def _numeric(value: Any) -> bool:
    return isinstance(value, (int, float, np.number)) and not pd.isna(value) and math.isfinite(float(value))


def _paired_data(frame: pd.DataFrame, metric: str) -> tuple[list[str], dict[str, list[float]]]:
    subset = frame[["participant", "condition", metric]].copy()
    subset = subset[subset["condition"].isin(CONDITIONS)]
    pivot = subset.pivot_table(index="participant", columns="condition", values=metric, aggfunc="mean")
    pivot = pivot.reindex(columns=CONDITIONS)
    complete = pivot.dropna(subset=CONDITIONS)
    return [str(x) for x in complete.index], {c: complete[c].astype(float).tolist() for c in CONDITIONS}


def run_statistics(participant_condition: pd.DataFrame) -> dict[str, Any]:
    results: dict[str, Any] = {
        "design": "within-subjects; non-parametric repeated measures",
        "condition_order": CONDITIONS,
        "primary_metrics": {},
        "notes": [
            "Friedman and post-hoc tests use participants with non-missing values in all three conditions.",
            "Post-hoc planned comparisons are run only when the omnibus Friedman p-value is below 0.05.",
            "H3 incorrect-rate and H4 perceived-control results are descriptive; non-significance is not evidence of equivalence.",
            "False EMG activations are not analysed unless logs explicitly identify real device EMG events during rest.",
        ],
    }
    for metric, label in PRIMARY_METRICS.items():
        entry: dict[str, Any] = {"label": label, "metric": metric, "n_complete": 0, "friedman": None, "kendalls_w": None, "posthoc": []}
        if metric not in participant_condition.columns:
            entry["status"] = "metric_unavailable"
            results["primary_metrics"][metric] = entry
            continue
        participants, values = _paired_data(participant_condition, metric)
        entry["n_complete"] = len(participants)
        entry["participants"] = participants
        if len(participants) < 3:
            entry["status"] = "insufficient_complete_participants_for_friedman"
            results["primary_metrics"][metric] = entry
            continue
        if all(
            np.isclose(values[CONDITIONS[0]][i], values[CONDITIONS[1]][i])
            and np.isclose(values[CONDITIONS[1]][i], values[CONDITIONS[2]][i])
            for i in range(len(participants))
        ):
            entry["status"] = "not_testable_no_within_subject_variation"
            results["primary_metrics"][metric] = entry
            continue
        try:
            test = friedmanchisquare(*(values[c] for c in CONDITIONS))
            chi2, pvalue = float(test.statistic), float(test.pvalue)
            entry["friedman"] = {"chi2": chi2, "p_value": pvalue, "df": 2}
            entry["kendalls_w"] = chi2 / (len(participants) * (len(CONDITIONS) - 1))
            entry["status"] = "tested"
        except (ValueError, ZeroDivisionError) as exc:
            entry["status"] = f"not_testable: {exc}"
            results["primary_metrics"][metric] = entry
            continue
        if pvalue < 0.05:
            raw = []
            for a, b in PLANNED_PAIRS:
                av, bv = values[a], values[b]
                diffs = [x - y for x, y in zip(av, bv)]
                try:
                    test_pair = wilcoxon(av, bv, zero_method="wilcox", alternative="two-sided", method="auto")
                    p_raw = float(test_pair.pvalue)
                    n_nonzero = sum(abs(d) > 0 for d in diffs)
                    zmag = float(norm.isf(p_raw / 2)) if p_raw > 0 else float("inf")
                    sign = 1 if (sum(diffs) >= 0) else -1
                    effect = sign * zmag / math.sqrt(n_nonzero) if n_nonzero else 0.0
                    raw.append({
                        "comparison": f"{a} vs {b}", "statistic": float(test_pair.statistic),
                        "p_raw": p_raw, "effect_r": effect, "n_nonzero_pairs": n_nonzero,
                        "median_difference_a_minus_b": float(np.median(diffs)) if diffs else None,
                    })
                except (ValueError, ZeroDivisionError) as exc:
                    raw.append({"comparison": f"{a} vs {b}", "status": f"not_testable: {exc}", "p_raw": None})
            valid_indices = [i for i, item in enumerate(raw) if item.get("p_raw") is not None]
            if valid_indices:
                adjusted = multipletests([raw[i]["p_raw"] for i in valid_indices], method="holm")[1]
                for i, p_adj in zip(valid_indices, adjusted):
                    raw[i]["p_holm"] = float(p_adj)
                    raw[i]["significant_holm_0_05"] = bool(p_adj < 0.05)
            entry["posthoc"] = raw
        else:
            entry["posthoc_status"] = "not_run_omnibus_not_significant"
        results["primary_metrics"][metric] = entry
    return results