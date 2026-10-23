"""Trial tasks and rest windows: the drawer controls that give Meghna's metrics their ground truth."""

import json

import pytest

from cavia.server.session import Session
from cavia.server.tasks import DEFAULT_TASKS, Task, load_tasks, parse_tasks


def task(**overrides):
    return {"id": "T1", "object": "cup", "region": "handle", "target_grip": "LATERAL", **overrides}


def test_default_task_file_is_valid():
    tasks = load_tasks(DEFAULT_TASKS)
    assert len(tasks) >= 1 and len({t.id for t in tasks}) == len(tasks)


def test_tasks_are_normalised():
    [t] = parse_tasks({"tasks": [task(object=" Cup ", region="HANDLE", target_grip="lateral")]})
    assert t == Task("T1", "cup", "handle", "LATERAL")


@pytest.mark.parametrize("bad, message", [
    ([], "tasks"),
    ({"tasks": [task(), task()]}, "duplicate"),
    ({"tasks": [task(id="")]}, "id"),
    ({"tasks": [task(object="plate")]}, "unknown object region"),
    ({"tasks": [task(region="cap")]}, "unknown object region"),
    ({"tasks": [task(target_grip="OPEN")]}, "calibrated"),
    ({"tasks": ["T1"]}, "object"),
])
def test_invalid_tasks_are_rejected(bad, message):
    with pytest.raises(ValueError, match=message):
        parse_tasks(bad)


def test_load_reads_json(tmp_path):
    path = tmp_path / "tasks.json"
    path.write_text(json.dumps({"tasks": [task()]}))
    assert load_tasks(path)[0].target_grip == "LATERAL"


class Clock:
    t = 100.0

    def __call__(self):
        return self.t


@pytest.fixture
def session():
    sent, audit = [], []
    clock = Clock()
    s = Session(lambda kind, data: sent.append((kind, data)), audit=lambda e, **d: audit.append((e, d)),
                tasks=parse_tasks({"tasks": [task(), task(id="T2", region="body", target_grip="POWER")]}),
                clock=clock)
    s.test = dict(sent=sent, audit=audit, clock=clock)
    return s


def test_announce_publishes_the_task_list(session):
    session.announce()
    kinds = [k for k, _ in session.test["sent"]]
    assert kinds == ["tasks", "session"]
    assert [t["id"] for t in session.test["sent"][0][1]["tasks"]] == ["T1", "T2"]


def test_trial_with_a_task_is_logged_for_analysis(session):
    session.control({"action": "start_trial", "task_id": "T2", "practice": True})
    assert session.state.task == {"id": "T2", "object": "cup", "region": "body", "target_grip": "POWER"}
    assert session.state.practice is True
    assert session.test["audit"][-1] == ("trial_start", {"trial": 1, "task_id": "T2", "object": "cup",
                                                         "region": "body", "target_grip": "POWER",
                                                         "practice": True})
    session.control({"action": "end_trial", "grasp_success": True})
    assert session.state.task is None and session.state.practice is False


def test_free_trial_keeps_the_same_log_shape(session):
    session.control({"action": "start_trial"})
    assert session.test["audit"][-1] == ("trial_start", {"trial": 1, "task_id": None, "object": None,
                                                         "region": None, "target_grip": None,
                                                         "practice": False})


def test_unknown_task_is_rejected_without_starting(session):
    with pytest.raises(ValueError, match="Unknown task"):
        session.control({"action": "start_trial", "task_id": "T9"})
    assert session.state.trial == 0 and not session.state.trial_active


def test_rest_window_is_timed_and_excludes_trials(session):
    session.control({"action": "start_rest"})
    assert session.state.rest_active and session.state.rest == 1
    with pytest.raises(ValueError, match="rest"):
        session.control({"action": "start_trial", "task_id": "T1"})
    with pytest.raises(ValueError, match="rest"):
        session.control({"action": "set_session", "participant": "P02", "condition": "C3_ADAPTIVE"})
    with pytest.raises(ValueError, match="already"):
        session.control({"action": "start_rest"})
    session.test["clock"].t += 60.25
    session.control({"action": "end_rest"})
    assert not session.state.rest_active
    assert session.test["audit"][-2:] == [("rest_start", {"rest": 1}), ("rest_end", {"rest": 1, "duration_s": 60.25})]
    with pytest.raises(ValueError, match="No rest"):
        session.control({"action": "end_rest"})


def test_no_rest_during_a_trial(session):
    session.control({"action": "start_trial"})
    with pytest.raises(ValueError, match="End the trial"):
        session.control({"action": "start_rest"})
