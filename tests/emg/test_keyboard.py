import pytest

from cavia.core.contracts import Activity, EmgEvent
from cavia.emg.keyboard import KeyboardEmg


@pytest.mark.parametrize("key, event", [
    ("w", EmgEvent.SE), ("s", EmgEvent.SF), ("a", EmgEvent.LF), ("d", EmgEvent.LE), ("e", EmgEvent.HE),
])
def test_gesture_mapping(key, event):
    assert KeyboardEmg().press(key) is event


def test_uppercase_counts_as_same_key():
    kb = KeyboardEmg()
    assert kb.press("S") is EmgEvent.SF
    kb.release("s")
    assert kb.held == set()


def test_one_press_gives_one_event():
    kb = KeyboardEmg()
    assert kb.press("s") is EmgEvent.SF
    assert kb.press("s") is None          # OS auto-repeat while held
    kb.release("s")
    assert kb.press("s") is EmgEvent.SF   # a new press is a new gesture


def test_non_gesture_keys_ignored():
    kb = KeyboardEmg()
    for key in ("f", "x", "m", "space", "1"):
        assert kb.press(key) is None
    assert kb.held == set()


def test_gesture_while_another_held_is_invalid():
    kb = KeyboardEmg()
    kb.press("a")
    assert kb.press("e") is EmgEvent.INVALID
    kb.release("a")
    kb.release("e")
    assert kb.press("e") is EmgEvent.HE


@pytest.mark.parametrize("held, activity", [
    (set(), Activity.REST),
    ({"a"}, Activity.FLEX_ACTIVE),
    ({"d"}, Activity.EXT_ACTIVE),
    ({"a", "d"}, Activity.INVALID),
    ({"w"}, Activity.REST),
    ({"e"}, Activity.REST),
])
def test_activity_from_held_keys(held, activity):
    kb = KeyboardEmg()
    kb.held = set(held)
    assert kb.activity() is activity


def test_release_all_on_focus_loss():
    kb = KeyboardEmg()
    kb.press("a")
    kb.press("d")
    kb.release_all()
    assert kb.activity() is Activity.REST
    assert kb.press("a") is EmgEvent.LF


def test_release_of_unheld_key_is_harmless():
    kb = KeyboardEmg()
    kb.release("a")
    assert kb.activity() is Activity.REST
