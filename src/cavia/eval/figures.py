"""Publication-oriented F1–F8 figures. Empty data produce labelled placeholders, never invented values."""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

COLORS = {"C1_MANUAL": "#78865A", "C2_STATIC": "#16845B", "C3_ADAPTIVE": "#A4D65E"}
LABELS = {"C1_MANUAL": "Manual", "C2_STATIC": "Static", "C3_ADAPTIVE": "Adaptive"}
ORDER = ["C1_MANUAL", "C2_STATIC", "C3_ADAPTIVE"]


def _placeholder(ax, title: str, ylabel: str = "") -> None:
    ax.set_title(title)
    ax.set_ylabel(ylabel)
    ax.text(0.5, 0.5, "Awaiting eligible study data", ha="center", va="center", transform=ax.transAxes, color="#666666")
    ax.set_xticks([])
    ax.set_yticks([])


def _save(fig, out: Path, name: str) -> None:
    fig.tight_layout()
    fig.savefig(out / f"{name}.png", dpi=180, bbox_inches="tight")
    fig.savefig(out / f"{name}.svg", bbox_inches="tight")
    plt.close(fig)


def _condition_values(frame: pd.DataFrame, metric: str) -> list[list[float]]:
    values = []
    for condition in ORDER:
        vals = frame.loc[frame["condition"] == condition, metric] if metric in frame else pd.Series(dtype=float)
        values.append([float(v) for v in vals if isinstance(v, (int, float, np.number)) and pd.notna(v)])
    return values


def _box_points(ax, frame: pd.DataFrame, metric: str, title: str, ylabel: str, zero: bool = False) -> None:
    values = _condition_values(frame, metric)
    positions = [1, 2, 3]
    if not any(values):
        _placeholder(ax, title, ylabel)
        return
    nonempty = [(p, v) for p, v in zip(positions, values) if v]
    boxes = ax.boxplot([v for _, v in nonempty], positions=[p for p, _ in nonempty], widths=0.5, patch_artist=True, showfliers=False)
    for patch, (pos, _) in zip(boxes["boxes"], nonempty):
        patch.set_facecolor(COLORS[ORDER[pos - 1]])
        patch.set_alpha(0.45)
    rng = np.random.default_rng(0)
    for pos, vals in nonempty:
        x = rng.normal(pos, 0.045, size=len(vals))
        ax.scatter(x, vals, color=COLORS[ORDER[pos - 1]], edgecolor="#333333", linewidth=0.4, zorder=3, label=f"n={len(vals)}")
    ax.set_title(title)
    ax.set_ylabel(ylabel)
    n_by_condition = {c: len(v) for c, v in zip(ORDER, values)}
    ax.set_xticks(positions, [f"{LABELS[c]}\nn={n_by_condition[c]}" for c in ORDER])
    if zero:
        ax.set_ylim(bottom=0)
    ax.grid(axis="y", alpha=0.25)


def generate_figures(trials: pd.DataFrame, aggregate: pd.DataFrame, out_dir: str | Path) -> list[str]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    eligible = trials[trials.get("analysis_eligible", pd.Series(False, index=trials.index)).fillna(False)].copy() if not trials.empty else trials.copy()
    generated = []

    fig, ax = plt.subplots(figsize=(7.2, 4.5))
    _box_points(ax, eligible, "commands", "F1. EMG commands per selection", "Commands / selection", True)
    _save(fig, out, "F1_commands")
    generated.append("F1_commands")

    fig, ax = plt.subplots(figsize=(7.2, 4.5))
    _box_points(ax, eligible, "selection_time_s", "F2. Grip selection time", "Seconds", True)
    _save(fig, out, "F2_selection_time")
    generated.append("F2_selection_time")

    fig, ax = plt.subplots(figsize=(8.2, 4.7))
    metrics = [("incorrect_rate", "Incorrect selection rate"), ("first_option_acceptance_rate", "First-option acceptance")]
    x = np.arange(3)
    width = 0.34
    any_data = False
    for j, (metric, label) in enumerate(metrics):
        means, errors = [], []
        for condition in ORDER:
            vals = []
            if metric in aggregate:
                vals = [float(v) for v in aggregate.loc[aggregate["condition"] == condition, metric]
                        if isinstance(v, (int, float, np.number)) and pd.notna(v)]
            means.append(float(np.mean(vals)) if vals else np.nan)
            errors.append(float(np.std(vals, ddof=1) / math.sqrt(len(vals))) if len(vals) > 1 else 0.0)
            any_data |= bool(vals)
        if any(not np.isnan(v) for v in means):
            ax.bar(x + (j - 0.5) * width, means, width, yerr=errors, capsize=3, label=label,
                   color=[COLORS[c] for c in ORDER], alpha=0.82 if j == 0 else 0.5,
                   edgecolor="#333333", linewidth=0.4)
    if not any_data:
        _placeholder(ax, "F3. Error and first-option rates", "Rate")
    else:
        ax.set_title("F3. Incorrect selection and first-option acceptance")
        ax.set_ylabel("Rate")
        ax.set_ylim(0, 1)
        n_by_condition = {c: int(aggregate.loc[aggregate["condition"] == c, "participant"].nunique()) if not aggregate.empty else 0 for c in ORDER}
        ax.set_xticks(x, [f"{LABELS[c]}\nn={n_by_condition[c]}" for c in ORDER])
        ax.legend()
        ax.grid(axis="y", alpha=0.25)
    _save(fig, out, "F3_error_acceptance")
    generated.append("F3_error_acceptance")

    fig, axes = plt.subplots(1, 2, figsize=(11, 4.5))
    for ax, metric, title, ylabel in [
        (axes[0], "commands_mean", "F4a. Commands by participant", "Mean commands / selection"),
        (axes[1], "selection_time_s_mean", "F4b. Selection time by participant", "Mean seconds"),
    ]:
        if aggregate.empty or metric not in aggregate or not aggregate[metric].notna().any():
            _placeholder(ax, title, ylabel)
            continue
        pivot = aggregate.pivot_table(index="participant", columns="condition", values=metric, aggfunc="mean").reindex(columns=ORDER)
        n_plotted = 0
        for _, participant_values in pivot.iterrows():
            y = [float(v) if pd.notna(v) else np.nan for v in participant_values.tolist()]
            if sum(not np.isnan(v) for v in y) >= 2:
                ax.plot([1, 2, 3], y, marker="o", linewidth=1, alpha=0.7, color="#555555")
                n_plotted += 1
        ax.set_title(title)
        ax.set_ylabel(ylabel)
        ax.set_xticks([1, 2, 3], [LABELS[c] for c in ORDER])
        ax.text(0.98, 0.98, f"n={n_plotted} participants", ha="right", va="top", transform=ax.transAxes, fontsize=8)
        ax.grid(axis="y", alpha=0.25)
    _save(fig, out, "F4_paired_participants")
    generated.append("F4_paired_participants")

    fig, axes = plt.subplots(1, 2, figsize=(11, 4.5))
    c3 = eligible[eligible["condition"] == "C3_ADAPTIVE"].copy() if not eligible.empty else eligible
    if c3.empty:
        _placeholder(axes[0], "F5a. Adaptation: commands", "Mean commands ± SE")
        _placeholder(axes[1], "F5b. Adaptation: selection time", "Mean seconds ± SE")
    else:
        c3["trial_index"] = c3.groupby("participant").cumcount() + 1
        for ax, metric, title, ylabel in [
            (axes[0], "commands", "F5a. Adaptation: commands", "Mean commands ± SE"),
            (axes[1], "selection_time_s", "F5b. Adaptation: selection time", "Mean seconds ± SE"),
        ]:
            grouped = c3.groupby("trial_index")[metric].agg(["mean", "std", "count"]).reset_index()
            grouped["se"] = grouped["std"].fillna(0) / np.sqrt(grouped["count"].clip(lower=1))
            ax.errorbar(grouped["trial_index"], grouped["mean"], yerr=grouped["se"], marker="o", capsize=2, color=COLORS["C3_ADAPTIVE"])
            ax.set_title(title)
            ax.set_xlabel("C3 measured-trial index")
            ax.set_ylabel(ylabel)
            ax.set_ylim(bottom=0)
            ax.text(0.98, 0.98, f"n={c3['participant'].nunique()} participants", ha="right", va="top", transform=ax.transAxes, fontsize=8)
            ax.grid(alpha=0.25)
    _save(fig, out, "F5_adaptation")
    generated.append("F5_adaptation")

    fig, ax = plt.subplots(figsize=(8, 4.7))
    if c3.empty or "policy" not in c3 or not c3["policy"].notna().any():
        _placeholder(ax, "F6. Menu policy share over C3 trial bins", "Share of menus")
    else:
        c3 = c3.sort_values(["participant", "trial_index"])
        max_idx = int(c3["trial_index"].max())
        bins = min(6, max(1, max_idx))
        c3["trial_bin"] = np.minimum(((c3["trial_index"] - 1) * bins // max_idx) + 1, bins)
        policy_names = ["ONE_CONFIRM", "TOP_TWO", "FULL_COMPATIBLE", "FULL_MENU"]
        shares = []
        labels = []
        for b in sorted(c3["trial_bin"].unique()):
            part = c3[c3["trial_bin"] == b]["policy"].astype(str)
            denom = int(part.notna().sum())
            labels.append(f"Bin {int(b)}")
            shares.append([float((part == p).sum() / denom) if denom else 0.0 for p in policy_names])
        bottom = np.zeros(len(labels))
        policy_colors = [COLORS["C3_ADAPTIVE"], "#16845B", "#78865A", "#9CA3AF"]
        for i, policy in enumerate(policy_names):
            vals = np.array([s[i] for s in shares])
            ax.bar(labels, vals, bottom=bottom, label=policy, color=policy_colors[i])
            bottom += vals
        ax.set_title("F6. Menu policy share over C3 trial bins")
        ax.set_ylabel("Share of menus")
        ax.set_ylim(0, 1)
        ax.legend(fontsize=8)
        ax.text(0.98, 0.98, f"n={c3['participant'].nunique()} participants", ha="right", va="top", transform=ax.transAxes, fontsize=8)
        ax.grid(axis="y", alpha=0.2)
    _save(fig, out, "F6_policy_share")
    generated.append("F6_policy_share")

    fig, axes = plt.subplots(2, 2, figsize=(10, 7))
    q_metrics = [
        ("raw_tlx", "NASA-TLX (raw; lower is better)", "0–100"),
        ("sus_score", "SUS (0–100)", "Score"),
        ("control_score", "Perceived control (1–7)", "Score"),
        ("confidence_score", "Confidence (1–7)", "Score"),
    ]
    for ax, (metric, title, ylabel) in zip(axes.flat, q_metrics):
        _box_points(ax, aggregate, metric, title, ylabel, False)
    _save(fig, out, "F7_questionnaires")
    generated.append("F7_questionnaires")

    fig, ax = plt.subplots(figsize=(8, 4.7))
    names = ["full_menu_rate", "override_rate"]
    vals_by_metric = []
    for metric in names:
        vals_by_metric.append([float(v) for v in aggregate[metric] if isinstance(v, (int, float, np.number)) and pd.notna(v)] if metric in aggregate else [])
    if not any(vals_by_metric):
        _placeholder(ax, "F8. Full-menu use and override rates", "Rate")
    else:
        x = np.arange(3)
        width = 0.35
        for j, metric in enumerate(names):
            means = []
            errors = []
            for cond in ORDER:
                vals = [float(v) for v in aggregate.loc[aggregate["condition"] == cond, metric] if isinstance(v, (int, float, np.number)) and pd.notna(v)] if metric in aggregate else []
                means.append(float(np.mean(vals)) if vals else np.nan)
                errors.append(float(np.std(vals, ddof=1) / math.sqrt(len(vals))) if len(vals) > 1 else 0.0)
            ax.bar(x + (j - 0.5) * width, means, width, yerr=errors, capsize=3,
                   label=("Full-menu rate" if j == 0 else "Override rate"),
                   color=[COLORS[c] for c in ORDER], alpha=0.82 if j == 0 else 0.5,
                   edgecolor="#333333", linewidth=0.4)
        ax.set_title("F8. Full-menu use and override rates")
        ax.set_ylabel("Rate")
        ax.set_ylim(0, 1)
        n_by_condition = {c: int(aggregate.loc[aggregate["condition"] == c, "participant"].nunique()) if not aggregate.empty else 0 for c in ORDER}
        ax.set_xticks(x, [f"{LABELS[c]}\nn={n_by_condition[c]}" for c in ORDER])
        ax.legend()
        ax.grid(axis="y", alpha=0.25)
    _save(fig, out, "F8_menu_overrides")
    generated.append("F8_menu_overrides")
    return generated