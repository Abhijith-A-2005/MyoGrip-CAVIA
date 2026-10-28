from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from cavia.eval.aggregate import aggregate_trials
from cavia.eval.__main__ import run as run_pipeline
from cavia.eval.loader import load_sessions, session_metadata
from cavia.eval.questionnaires import score_questionnaire_row
from cavia.eval.stats import run_statistics
from cavia.eval.trials import segment_trials


def rec(ts, kind, data=None, *, trial=1, condition="C3_ADAPTIVE", session="s1", user="P01", rest=None):
    return {
        "wall": 1000 + ts, "ts": ts, "session": session, "user": user,
        "condition": condition, "trial": trial, "rest": rest, "type": kind, "data": data or {},
        "_source_file": f"{session}.jsonl", "_line": int(ts * 100) + 1,
    }


def menu(ts, menu_id, items, policy="TOP_TWO", **extra):
    return rec(ts, "menu", {
        "menu_id": menu_id, "policy": policy, "items": items, "scores": [1 / len(items)] * len(items),
        "confidence": {"vision": 0.8, "evidence_n": 3}, "context": {"object": "cup", "region": "handle"},
        "compatible": ["POWER", "PINCH", "TRIPOD"], "ranking_source": "region", "region_evidence_n": 3, **extra,
    })


def basic_trial():
    return [
        rec(0.0, "session_start", {"participant": "P01", "condition": "C3_ADAPTIVE"}, trial=None),
        rec(1.0, "trial_start", {"trial": 1, "task_id": "T1", "object": "cup", "region": "handle", "target_grip": "TRIPOD", "practice": False}),
        rec(1.5, "vision", {"state": "LOCKED", "object": "cup", "region": "handle"}),
        menu(2.0, 1, ["POWER", "TRIPOD"]),
        rec(2.5, "key_down", {"key": "s", "menu_id": 1}),
        rec(3.0, "key_down", {"key": "a", "menu_id": 1}),
        rec(3.0, "confirmed", {"menu_id": 1, "interaction_id": "i1", "grip": "TRIPOD"}),
        rec(3.2, "preference_update", {"selection": {"grip": "TRIPOD", "from_full_menu": False, "compatible": True, "status": "accepted"}}),
        rec(4.0, "trial_end", {"trial": 1, "grasp_success": True, "notes": ""}, trial=None),
    ]


def process(records):
    metadata = session_metadata(records)
    trials, rests = segment_trials(records, metadata)
    return trials, rests


def test_trial_metrics_commands_time_menu_target_grasp_and_selection_status():
    trials, _ = process(basic_trial())
    row = trials[0]
    assert row["status"] == "valid"
    assert row["commands"] == 2
    assert row["nav_commands"] == 1
    assert row["confirm_commands"] == 1
    assert row["selection_time_s"] == pytest.approx(1.0)
    assert row["task_time_s"] == pytest.approx(3.0)
    assert row["t_lock_s"] == pytest.approx(0.5)
    assert row["incorrect"] is False
    assert row["corrected"] is False
    assert row["target_in_menu"] is True
    assert row["target_rank"] == 2
    assert row["first_option_accepted"] is False
    assert row["from_full_menu"] is False
    assert row["override"] is False
    assert row["compatible"] is True
    assert row["selection_status"] == "accepted"
    assert row["grasp_success"] is True
    assert row["policy"] == "TOP_TWO"
    assert row["menu_len"] == 2
    assert row["confidence_vision"] == pytest.approx(0.8)
    assert row["region_evidence_n"] == 3


def test_menu_replacement_uses_confirmed_menu_id_not_latest_guess():
    records = [
        rec(0, "trial_start", {"trial": 1, "target_grip": "TRIPOD", "practice": False}),
        rec(0.5, "vision", {"state": "LOCKED"}),
        menu(1.0, 10, ["POWER"]),
        menu(1.5, 11, ["POWER", "PINCH", "TRIPOD"]),
        rec(2.0, "key_down", {"key": "a", "menu_id": 11}),
        rec(2.0, "confirmed", {"menu_id": 11, "grip": "TRIPOD"}),
        rec(3.0, "trial_end", {"trial": 1, "grasp_success": True}, trial=None),
    ]
    row = process(records)[0][0]
    assert row["menu_len"] == 3
    assert row["target_rank"] == 3
    assert row["target_in_menu"] is True
    assert row["first_option_accepted"] is False


def test_first_option_acceptance_requires_no_navigation():
    records = [
        rec(0, "trial_start", {"trial": 1, "target_grip": "POWER", "practice": False}),
        menu(1, 1, ["POWER", "PINCH"]),
        rec(2, "key_down", {"key": "a", "menu_id": 1}),
        rec(2, "confirmed", {"menu_id": 1, "grip": "POWER"}),
        rec(3, "trial_end", {"trial": 1}, trial=None),
    ]
    row = process(records)[0][0]
    assert row["commands"] == 1
    assert row["first_option_accepted"] is True
    assert row["target_rank"] == 1

def test_no_lock_no_confirm_and_aborted_trials_are_classified_not_dropped():
    records = [
        rec(0, "trial_start", {"trial": 1, "practice": False}),
        rec(2, "trial_end", {"trial": 1}, trial=None),
        rec(3, "trial_start", {"trial": 2, "practice": False}, trial=2),
        rec(3.5, "vision", {"state": "LOCKED"}, trial=2),
        menu(4, 2, ["POWER"], trial=2),
        rec(5, "trial_end", {"trial": 2}, trial=None),
        rec(6, "trial_start", {"trial": 3, "practice": False}, trial=3),
        rec(6.5, "note", {"message": "Trial aborted by experimenter"}, trial=3),
        rec(7, "trial_end", {"trial": 3}, trial=None),
    ]
    rows, _ = process(records)
    assert [r["status"] for r in rows] == ["no_lock", "no_confirm", "aborted"]


def test_multiple_confirmations_detect_corrected_error_and_keep_final_grip():
    records = [
        rec(0, "trial_start", {"trial": 1, "target_grip": "TRIPOD", "practice": False}),
        menu(1, 1, ["POWER", "TRIPOD"]),
        rec(2, "key_down", {"key": "a", "menu_id": 1}),
        rec(2, "confirmed", {"menu_id": 1, "interaction_id": "i1", "grip": "POWER"}),
        rec(2.5, "key_down", {"key": "e", "menu_id": 1}),
        menu(3, 2, ["TRIPOD", "POWER"]),
        rec(4, "key_down", {"key": "a", "menu_id": 2}),
        rec(4, "confirmed", {"menu_id": 2, "interaction_id": "i2", "grip": "TRIPOD"}),
        rec(5, "trial_end", {"trial": 1}, trial=None),
    ]
    row = process(records)[0][0]
    assert row["confirmed_grip"] == "POWER"
    assert row["final_grip"] == "TRIPOD"
    assert row["incorrect"] is True
    assert row["corrected"] is True
    assert row["commands"] == 1  # exact brief definition stops at first confirmation


def test_free_trial_incorrect_is_na_and_missing_optional_fields_do_not_crash():
    records = [
        rec(0, "trial_start", {"trial": 1, "task_id": None, "target_grip": None, "practice": False}),
        menu(1, 1, ["POWER"]),
        rec(2, "confirmed", {"menu_id": 1, "grip": "POWER"}),
        rec(3, "trial_end", {"trial": 1}, trial=None),
    ]
    row = process(records)[0][0]
    assert row["status"] == "valid"
    assert row["incorrect"] is None
    assert row["target_in_menu"] is None


def test_full_menu_override_incompatible_and_cancelled_metrics():
    records = [
        rec(0, "trial_start", {"trial": 1, "target_grip": "TRIPOD", "practice": False}),
        menu(1, 1, ["POWER", "PINCH"]),
        rec(2, "key_down", {"key": "d", "menu_id": 1}),
        rec(3, "key_down", {"key": "a", "menu_id": 1}),
        rec(3, "confirmed", {"menu_id": 1, "grip": "TRIPOD"}),
        rec(3.5, "preference_update", {"selection": {"grip": "TRIPOD", "from_full_menu": True, "compatible": False, "status": "cancelled"}}),
        rec(4, "trial_end", {"trial": 1, "grasp_success": False}, trial=None),
    ]
    row = process(records)[0][0]
    assert row["full_opens"] == 1
    assert row["from_full_menu"] is True
    assert row["override"] is True
    assert row["compatible"] is False
    assert row["selection_status"] == "cancelled"
    assert row["grasp_success"] is False


def test_practice_and_technical_fault_are_excluded_but_time_cap_is_only_flagged():
    records = [
        rec(0, "trial_start", {"trial": 1, "target_grip": "POWER", "practice": True}),
        menu(1, 1, ["POWER"]),
        rec(62, "confirmed", {"menu_id": 1, "grip": "POWER"}),
        rec(63, "trial_end", {"trial": 1, "notes": "camera dropout"}, trial=None),
    ]
    row = process(records)[0][0]
    assert row["practice"] is True
    assert row["technical_fault"] is True
    assert row["analysis_eligible"] is False
    assert row["selection_time_flag"] == "over_60s"


def test_rest_window_keyboard_events_are_not_reported_as_real_false_emg():
    records = [
        rec(0, "rest_start", {"rest": 1}, trial=None, rest=1),
        rec(2, "key_down", {"key": "a", "source": "keyboard"}, trial=None, rest=1),
        rec(60, "rest_end", {"rest": 1, "duration_s": 60}, trial=None),
    ]
    _, rests = process(records)
    assert len(rests) == 1
    assert rests[0]["false_activations_per_min"] is None
    assert rests[0]["source_verified_device"] is False


def test_real_device_rest_event_can_be_counted_when_explicitly_identified():
    records = [
        rec(0, "rest_start", {"rest": 1}, trial=None, rest=1),
        rec(30, "emg", {"source": "device", "event": "SF"}, trial=None, rest=1),
        rec(60, "rest_end", {"rest": 1, "duration_s": 60}, trial=None),
    ]
    _, rests = process(records)
    assert rests[0]["false_activations_per_min"] == pytest.approx(1.0)
    assert rests[0]["source_verified_device"] is True


def test_loader_counts_malformed_lines_and_preserves_records(tmp_path):
    log = tmp_path / "session.jsonl"
    log.write_text(
        json.dumps({"ts": 1, "session": "s", "user": "P01", "condition": "C3_ADAPTIVE", "type": "note", "data": {}}) +
        "\n{bad json\n" +
        json.dumps({"ts": 2, "type": "note", "data": []}) + "\n",
        encoding="utf-8",
    )
    records, report = load_sessions(tmp_path)
    assert len(records) == 1
    assert report["malformed_json_lines"] == 1
    assert report["invalid_records"] == 1
    assert report["records_loaded"] == 1


def test_session_start_participant_overrides_runtime_user_alias():
    records = [
        rec(0, "note", {}, user="1"),
        rec(1, "session_start", {"participant": "P03", "condition": "C3_ADAPTIVE"}, user="1"),
    ]
    assert session_metadata(records)["s1"]["participant"] == "P03"


def test_questionnaire_scores_tlx_sus_control_confidence():
    row = {key: 50 for key in ["tlx_mental", "tlx_physical", "tlx_temporal", "tlx_performance", "tlx_effort", "tlx_frustration"]}
    row.update({f"sus_{i}": (5 if i % 2 else 1) for i in range(1, 11)})
    row.update({f"control_{i}": 7 for i in range(1, 5)})
    row.update({f"confidence_{i}": 6 for i in range(1, 4)})
    scored = score_questionnaire_row(row)
    assert scored["raw_tlx"] == 50
    assert scored["sus_score"] == 100
    assert scored["control_score"] == 7
    assert scored["confidence_score"] == 6
    assert scored["questionnaire_issues"] == ""


def test_incomplete_questionnaires_remain_unscored_not_imputed():
    scored = score_questionnaire_row({"participant": "P01", "condition": "C3_ADAPTIVE"})
    assert scored["raw_tlx"] is None
    assert scored["sus_score"] is None
    assert scored["control_score"] is None
    assert "missing" in scored["questionnaire_issues"]


def test_aggregate_rates_and_practice_exclusion():
    rows = [
        {"participant": "P01", "condition": "C3_ADAPTIVE", "order_position": 1, "practice": False, "status": "valid",
         "analysis_eligible": True, "commands": 2, "selection_time_s": 1.5, "incorrect": False, "corrected": False,
         "first_option_accepted": True, "target_rank": 1, "from_full_menu": False, "override": False,
         "compatible": True, "grasp_success": True, "selection_status": "accepted", "menu_len": 1, "policy": "ONE_CONFIRM",
         "target_in_menu": True, "technical_fault": False},
        {"participant": "P01", "condition": "C3_ADAPTIVE", "order_position": 1, "practice": True, "status": "valid",
         "analysis_eligible": False, "commands": 1, "selection_time_s": 1.0, "incorrect": False},
    ]
    frame = aggregate_trials(rows)
    assert frame.iloc[0]["trials_total"] == 1
    assert frame.iloc[0]["commands_mean"] == 2
    assert frame.iloc[0]["incorrect_rate"] == 0
    assert frame.iloc[0]["first_option_acceptance_rate"] == 1
    assert frame.iloc[0]["policy_one_confirm_count"] == 1
    assert frame.iloc[0]["target_suggestion_hit_rate"] == 1


def test_statistics_do_not_invent_comparisons_when_conditions_missing():
    frame = pd.DataFrame([{"participant": "P01", "condition": "C3_ADAPTIVE", "commands_mean": 2}])
    result = run_statistics(frame)
    assert result["primary_metrics"]["commands_mean"]["status"] == "insufficient_complete_participants_for_friedman"



def test_statistics_runs_friedman_and_planned_posthoc_on_complete_synthetic_panel():
    rows = []
    for i in range(6):
        rows.extend([
            {"participant": f"P{i+1:02d}", "condition": "C1_MANUAL", "commands_mean": 6 + i, "selection_time_s_mean": 8 + i, "incorrect_rate": 0.2, "control_score": 4.5},
            {"participant": f"P{i+1:02d}", "condition": "C2_STATIC", "commands_mean": 4 + i, "selection_time_s_mean": 5 + i, "incorrect_rate": 0.15, "control_score": 5.0},
            {"participant": f"P{i+1:02d}", "condition": "C3_ADAPTIVE", "commands_mean": 1 + i, "selection_time_s_mean": 2 + i, "incorrect_rate": 0.1, "control_score": 5.5},
        ])
    result = run_statistics(pd.DataFrame(rows))
    metric = result["primary_metrics"]["commands_mean"]
    assert metric["n_complete"] == 6
    assert metric["friedman"] is not None
    assert "kendalls_w" in metric
    if metric["friedman"]["p_value"] < 0.05:
        assert len(metric["posthoc"]) == 2
        assert all("p_holm" in pair for pair in metric["posthoc"])


def test_end_to_end_pipeline_writes_required_outputs_without_touching_input(tmp_path):
    source = tmp_path / "sessions"
    source.mkdir()
    log = source / "session.jsonl"
    rows = basic_trial()
    # Remove test-only loader annotations before writing a realistic JSONL source.
    serializable = [{k: v for k, v in row.items() if not k.startswith("_")} for row in rows]
    log.write_text("".join(json.dumps(row) + "\n" for row in serializable), encoding="utf-8")
    before = log.read_bytes()
    out = tmp_path / "results"
    result = run_pipeline(source, out)
    assert result["trials"] == 1
    assert len(result["figures"]) == 8
    for name in [
        "trials.csv", "participant_condition.csv", "questionnaires_scored.csv", "rest_windows.csv",
        "exclusions.csv", "descriptive_stats.csv", "descriptive_stats.md", "stats.json", "stats.md",
        "quality_report.json", "results.json",
    ]:
        assert (out / name).is_file(), name
    for figure in result["figures"]:
        assert (out / "figures" / f"{figure}.png").is_file()
        assert (out / "figures" / f"{figure}.svg").is_file()
    assert log.read_bytes() == before



def test_empty_questionnaire_csv_is_valid_and_produces_no_fake_scores(tmp_path):
    from cavia.eval.questionnaires import load_and_score_questionnaires

    csv_path = tmp_path / "questionnaires.csv"
    headers = ["participant", "condition"] + [f"tlx_{x}" for x in ["mental", "physical", "temporal", "performance", "effort", "frustration"]]
    csv_path.write_text(",".join(headers) + "\n", encoding="utf-8")
    scored, issues = load_and_score_questionnaires(csv_path)
    assert scored.empty
    assert "raw_tlx" in scored.columns
    assert issues == []



def test_statistics_handles_all_tied_repeated_measures_without_nan():
    rows = []
    for i in range(4):
        for condition in ["C1_MANUAL", "C2_STATIC", "C3_ADAPTIVE"]:
            rows.append({"participant": f"P{i+1:02d}", "condition": condition, "commands_mean": 2})
    result = run_statistics(pd.DataFrame(rows))
    entry = result["primary_metrics"]["commands_mean"]
    assert entry["status"] == "not_testable_no_within_subject_variation"
    assert entry["friedman"] is None