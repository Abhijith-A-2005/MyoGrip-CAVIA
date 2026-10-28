"""Validated questionnaire scoring; incomplete responses remain unscored."""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import pandas as pd

TLX_ITEMS = ["tlx_mental", "tlx_physical", "tlx_temporal", "tlx_performance", "tlx_effort", "tlx_frustration"]
SUS_ITEMS = [f"sus_{i}" for i in range(1, 11)]
CONTROL_ITEMS = [f"control_{i}" for i in range(1, 5)]
CONFIDENCE_ITEMS = [f"confidence_{i}" for i in range(1, 4)]
KEYS = ["participant", "condition"]


def score_questionnaire_row(row: dict[str, Any]) -> dict[str, Any]:
    result = dict(row)
    issues: list[str] = []
    def values(items: list[str], lo: float, hi: float, label: str) -> list[float] | None:
        vals = []
        for key in items:
            value = row.get(key)
            if value is None or (isinstance(value, float) and math.isnan(value)) or str(value).strip() == "":
                issues.append(f"{label}: missing {key}")
                return None
            try:
                number = float(value)
            except (TypeError, ValueError):
                issues.append(f"{label}: non-numeric {key}")
                return None
            if not lo <= number <= hi:
                issues.append(f"{label}: {key} outside {lo:g}–{hi:g}")
                return None
            vals.append(number)
        return vals
    tlx = values(TLX_ITEMS, 0, 100, "NASA-TLX")
    if tlx is not None:
        if any(v % 5 != 0 for v in tlx):
            issues.append("NASA-TLX values should use increments of 5")
        result["raw_tlx"] = sum(tlx) / 6
    else:
        result["raw_tlx"] = None
    sus = values(SUS_ITEMS, 1, 5, "SUS")
    if sus is not None:
        if any(not float(v).is_integer() for v in sus):
            issues.append("SUS responses should be integers 1–5")
        result["sus_score"] = sum((v - 1) if i % 2 == 0 else (5 - v) for i, v in enumerate(sus)) * 2.5
    else:
        result["sus_score"] = None
    control = values(CONTROL_ITEMS, 1, 7, "perceived control")
    result["control_score"] = sum(control) / len(control) if control is not None else None
    confidence = values(CONFIDENCE_ITEMS, 1, 7, "confidence")
    result["confidence_score"] = sum(confidence) / len(confidence) if confidence is not None else None
    result["questionnaire_issues"] = "; ".join(issues)
    return result


def load_and_score_questionnaires(path: str | Path) -> tuple[pd.DataFrame, list[str]]:
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(f"Questionnaire CSV does not exist: {source}")
    frame = pd.read_csv(source)
    missing = [key for key in KEYS if key not in frame.columns]
    if missing:
        raise ValueError("Questionnaire CSV missing required columns: " + ", ".join(missing))
    frame["participant"] = frame["participant"].astype(str).str.strip()
    frame["condition"] = frame["condition"].astype(str).str.strip()
    scored_rows = [score_questionnaire_row(row) for row in frame.to_dict(orient="records")]
    if scored_rows:
        scored = pd.DataFrame(scored_rows)
    else:
        scored = pd.DataFrame(columns=list(frame.columns) + [
            "raw_tlx", "sus_score", "control_score", "confidence_score", "questionnaire_issues"
        ])
    issues = []
    for idx, row in scored.iterrows():
        if row.get("questionnaire_issues"):
            issues.append(f"row {idx + 2} ({row.get('participant')}, {row.get('condition')}): {row['questionnaire_issues']}")
    duplicate = scored.duplicated(KEYS, keep=False)
    if duplicate.any():
        issues.append("Duplicate participant × condition questionnaire rows: " + ", ".join(
            f"{r.participant}/{r.condition}" for r in scored.loc[duplicate, KEYS].itertuples(index=False)
        ))
    return scored, issues