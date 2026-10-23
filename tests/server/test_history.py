"""History page data: selections joined with their menus, read without the runtime's store."""

from cavia.arbitration import ArbitrationEngine, ArbitrationInput, PreferenceStore
from cavia.core.contracts import Grip
from cavia.server.history import read_history


def make_history(db):
    with PreferenceStore(db) as store:
        engine = ArbitrationEngine(store)
        store.add_user("P02")
        steps = [("P01", Grip.LATERAL, False, "accepted"), ("P01", Grip.LATERAL, False, "accepted"),
                 ("P01", Grip.POWER, True, "accepted"), ("P01", Grip.PINCH, False, "cancelled")]
        for i, (user, grip, full, outcome) in enumerate(steps):
            menu = engine.propose(ArbitrationInput(user, "cup", "handle", 0.9)).proposal
            if not full and grip not in menu.items:
                grip = menu.items[0]
            engine.confirm(menu.menu_id, grip, f"t{i}", from_full_menu=full)
            engine.finish(f"t{i}", outcome)


def test_history_is_newest_first_with_menu_details(tmp_path):
    db = tmp_path / "prefs.sqlite3"
    make_history(db)
    h = read_history(db, "P01")
    rows = h["selections"]
    assert [r["id"] for r in rows] == ["t3", "t2", "t1", "t0"]
    assert rows[0]["status"] == "cancelled"
    assert rows[1]["menu"] == "full" and rows[1]["rank"] is None and rows[1]["compatible"] is False
    first = rows[-1]
    assert first["menu"] == "adaptive" and first["rank"] == first["items"].index(first["grip"]) + 1
    assert first["object"] == "cup" and first["region"] == "handle" and first["policy"]
    assert first["region_confidence"] == 0.9 and first["grasp_success"] is None
    assert h["summary"] == {"total": 4, "accepted": 3, "cancelled": 1, "adaptive": 3, "full": 1,
                            "first_option": sum(r["rank"] == 1 for r in rows)}
    # Only accepted, compatible, non-instructed choices count, as in the ranking.
    assert sum(p["n"] for p in h["preferences"]) == 2
    assert all(p["object"] == "cup" and p["region"] == "handle" for p in h["preferences"])


def test_user_without_history_and_missing_database(tmp_path):
    db = tmp_path / "prefs.sqlite3"
    make_history(db)
    assert read_history(db, "P02")["selections"] == []
    empty = read_history(tmp_path / "missing.sqlite3", "P01")
    assert empty["selections"] == [] and empty["summary"]["total"] == 0
    assert not (tmp_path / "missing.sqlite3").exists()
