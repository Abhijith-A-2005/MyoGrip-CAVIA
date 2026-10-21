"""Behaviour tests: run with unittest or the repository's existing pytest setup."""

import math
from pathlib import Path
import tempfile
import unittest

from cavia.arbitration import ArbitrationEngine, ArbitrationInput, ArbitrationConfig, PreferenceStore
from cavia.arbitration.demo import ArbitrationSimApp
from cavia.core.contracts import Grip, FsmState, MenuPolicy


class ArbitrationTests(unittest.TestCase):
    def setUp(self):
        self.store = PreferenceStore(":memory:")
        self.engine = ArbitrationEngine(self.store)
        self.sequence = 0

    def tearDown(self):
        self.store.close()

    def proposal(self, region="unknown", user="1", object="cup", vision=None):
        return self.engine.propose(ArbitrationInput(user, object, region, vision))

    def learn(self, grip, region="handle", user="1", n=1, object="cup", outcome="accepted", instructed=False):
        for _ in range(n):
            self.sequence += 1
            menu = self.proposal(region, user, object)
            interaction = f"trial-{self.sequence}"
            self.engine.confirm(menu.proposal.menu_id, grip, interaction, from_full_menu=True, instructed=instructed)
            self.engine.finish(interaction, outcome)
        return interaction

    def test_input_normalization(self):
        r = ArbitrationInput(1, " MUG ", " side_EDGE ")
        self.assertEqual((r.user, r.object, r.region), ("1", "cup", "side_edge"))
        self.assertEqual(ArbitrationInput("P01", "phone", None).region, "unknown")

    def test_invalid_inputs(self):
        for confidence in [math.nan, math.inf, -0.1, 1.01, True, "0.9"]:
            with self.subTest(confidence=confidence), self.assertRaises(ValueError):
                ArbitrationInput(1, "cup", "handle", confidence)
        for user in [True, "", None, []]:
            with self.subTest(user=user), self.assertRaises(ValueError):
                ArbitrationInput(user, "cup")
        with self.assertRaises(ValueError):
            self.engine.propose(ArbitrationInput(1, "cup", stable=False))

    def test_config_validation(self):
        for kwargs in [{"alpha": 0}, {"alpha": math.nan}, {"region_history_min": 0},
                       {"shortcut_vision": 0.1}, {"shortcut_evidence": 1}, {"shortcut_share": 1.1}]:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                ArbitrationConfig(**kwargs)

    def test_cold_start_default_order(self):
        d = self.proposal()
        self.assertEqual(d.proposal.items, [Grip.POWER, Grip.LATERAL, Grip.PINCH])
        self.assertEqual(d.ranking_source, "default")
        self.assertEqual(d.proposal.policy, MenuPolicy.FULL_COMPATIBLE)
        self.assertEqual(len(self.store.history()), 0)
        self.assertTrue(all(abs(s - 1/3) < 1e-9 for s in d.proposal.scores))

    def test_object_aggregates_regions_once(self):
        self.learn("PINCH", n=8)
        self.learn("POWER", region="body", n=3)
        d = self.proposal()
        self.assertEqual(d.proposal.items, [Grip.PINCH, Grip.POWER, Grip.LATERAL])
        self.assertEqual(d.proposal.confidence.evidence_n, 11)
        self.assertEqual(len(self.store.history()), 11)
        self.assertEqual(d.proposal.policy, MenuPolicy.FULL_COMPATIBLE)

    def test_region_preference_takes_priority(self):
        self.learn("LATERAL", region="body", n=12)
        self.learn("PINCH", region="handle", n=3)
        self.assertEqual(self.proposal().proposal.items[0], Grip.LATERAL)
        d = self.proposal("handle")
        self.assertEqual(d.ranking_source, "region")
        self.assertEqual(d.proposal.items[0], Grip.PINCH)

    def test_sparse_region_uses_object_fallback(self):
        self.learn("LATERAL", region="body", n=8)
        self.learn("PINCH", n=1)
        d = self.proposal("handle", vision=0.99)
        self.assertEqual(d.ranking_source, "object")
        self.assertEqual(d.region_evidence_n, 1)
        self.assertEqual(d.proposal.items[0], Grip.LATERAL)
        self.assertEqual(d.proposal.policy, MenuPolicy.FULL_COMPATIBLE)

    def test_unknown_region_does_not_invent_handle_history(self):
        self.learn("PINCH", region="unknown", n=10)
        d = self.proposal("handle", vision=0.99)
        self.assertEqual(d.proposal.items[0], Grip.PINCH)
        self.assertEqual(d.region_evidence_n, 0)
        self.assertEqual(d.proposal.policy, MenuPolicy.FULL_COMPATIBLE)

    def test_no_cross_user_leakage(self):
        self.learn("PINCH", n=8)
        d = self.proposal(user="2")
        self.assertEqual(d.proposal.confidence.evidence_n, 0)
        self.assertEqual(d.proposal.items[0], Grip.POWER)

    def test_names_with_sql_characters_are_data(self):
        user = "P01' OR 1=1 --"
        self.learn("PINCH", user=user, n=3)
        self.assertEqual(self.store.counts(user, "cup"), {"PINCH": 3})
        self.assertEqual(self.store.counts("1", "cup"), {})

    def test_compatibility_beats_popularity(self):
        self.learn("PINCH", n=20)
        d = self.proposal("body")
        self.assertNotIn(Grip.PINCH, d.proposal.items)
        self.assertEqual(d.proposal.confidence.evidence_n, 0)

    def test_missing_and_low_confidence_prevent_shortcut(self):
        self.learn("PINCH", n=8)
        for confidence in [None, 0.59]:
            d = self.proposal("handle", vision=confidence)
            self.assertEqual(d.proposal.policy, MenuPolicy.FULL_COMPATIBLE)

    def test_one_confirm_requires_region_evidence(self):
        self.learn("PINCH", n=5)
        d = self.proposal("handle", vision=0.9)
        self.assertEqual(d.proposal.policy, MenuPolicy.ONE_CONFIRM)
        self.assertEqual(d.proposal.items, [Grip.PINCH])
        self.assertAlmostEqual(d.proposal.scores[0], 6/7)
        self.assertEqual(d.proposal.full_menu, [Grip.POWER, Grip.PINCH, Grip.TRIPOD, Grip.LATERAL])

    def test_top_two_three_candidate_region(self):
        self.learn("TRIPOD", object="toothbrush", n=2)
        self.learn("LATERAL", object="toothbrush")
        self.learn("PINCH", object="toothbrush")
        d = self.proposal("handle", object="toothbrush", vision=0.9)
        self.assertEqual(d.proposal.policy, MenuPolicy.TOP_TWO)
        self.assertEqual(d.proposal.items, [Grip.TRIPOD, Grip.LATERAL])
        self.assertEqual(len(d.compatible), 3)

    def test_single_candidate_is_not_learned_shortcut(self):
        d = self.proposal("body", object="bottle")
        self.assertEqual(d.proposal.items, [Grip.POWER])
        self.assertEqual(d.proposal.policy, MenuPolicy.FULL_COMPATIBLE)
        self.assertEqual(d.reason, "single_compatible_grip")

    def test_unknown_object_and_region_fallback(self):
        d = self.proposal(object="pen")
        self.assertEqual(d.proposal.policy, MenuPolicy.FULL_MENU)
        self.assertEqual(d.proposal.items, [])
        d = self.proposal("rim")
        self.assertEqual(d.proposal.context.region, "unknown")
        self.assertEqual(d.requested_region, "rim")

    def test_availability_filter(self):
        engine = ArbitrationEngine(self.store, available_grips=[Grip.PINCH])
        d = engine.propose({"user": 1, "object": "cup", "region": "handle"})
        self.assertEqual(d.proposal.items, [Grip.PINCH])
        self.assertEqual(d.proposal.full_menu, [Grip.PINCH])
        engine = ArbitrationEngine(self.store, available_grips=[Grip.TRIPOD])
        self.assertEqual(engine.propose({"user": 1, "object": "cup"}).proposal.policy, MenuPolicy.FULL_MENU)
        for available in [[], [Grip.OPEN], [Grip.PINCH, Grip.PINCH], [2]]:
            with self.assertRaises(ValueError):
                ArbitrationEngine(self.store, available_grips=available)

    def test_pending_not_counted(self):
        d = self.proposal("handle")
        self.engine.confirm(d.proposal.menu_id, "PINCH", "pending")
        self.assertEqual(self.store.counts("1", "cup"), {})
        self.assertEqual(self.store.get_selection("pending")["status"], "pending")

    def test_duplicate_confirmation_and_feedback_are_idempotent(self):
        d = self.proposal("handle")
        for _ in range(3):
            self.engine.confirm(d.proposal.menu_id, "PINCH", "same")
            self.engine.finish("same", "accepted")
        self.assertEqual(self.store.counts("1", "cup"), {"PINCH": 1})
        with self.assertRaises(ValueError):
            self.engine.confirm(d.proposal.menu_id, "LATERAL", "same")
        self.assertEqual(self.store.counts("1", "cup"), {"PINCH": 1})

    def test_cancellation_failure_and_instructions_not_learned(self):
        self.learn("PINCH", outcome="cancelled")
        self.learn("PINCH", outcome="failed")
        self.learn("PINCH", instructed=True)
        self.assertEqual(self.store.counts("1", "cup"), {})
        self.assertEqual(len(self.store.history()), 3)

    def test_late_failure_removes_preference_without_losing_history(self):
        interaction = self.learn("PINCH")
        self.engine.finish(interaction, "failed", grasp_success=False)
        self.assertEqual(self.store.counts("1", "cup"), {})
        self.assertEqual(len(self.store.history()), 1)
        with self.assertRaises(ValueError):
            self.engine.finish(interaction, "accepted")

    def test_full_menu_incompatible_override_logged_not_learned(self):
        interaction = self.learn("POWER", region="handle")
        row = self.store.get_selection(interaction)
        self.assertEqual(row["compatible"], 0)
        self.assertEqual(self.store.counts("1", "cup"), {})

    def test_invalid_feedback_rejected(self):
        d = self.proposal("handle")
        for grip in ["body", "OPEN", "POWER"]:
            with self.assertRaises(ValueError):
                self.engine.confirm(d.proposal.menu_id, grip, "bad")
        with self.assertRaises(KeyError):
            self.engine.confirm(99999, "PINCH", "missing")
        self.engine.confirm(d.proposal.menu_id, "PINCH", "p")
        with self.assertRaises(ValueError):
            self.engine.finish("p", "accepted", grasp_success=False)
        self.assertEqual(self.store.history()[0]["status"], "pending")

    def test_original_snapshot_is_used_after_new_context_and_mutation(self):
        d = self.proposal("handle", user="1")
        menu_id = d.proposal.menu_id
        self.proposal("body", user="2")
        d.proposal.context.region = "body"
        d.proposal.items.clear()
        row = self.engine.confirm(menu_id, "PINCH", "old-context")
        self.assertEqual((row["user"], row["region"]), ("1", "handle"))

    def test_restart_persistence_and_monotonic_menu_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "history.sqlite3"
            with PreferenceStore(db) as store:
                engine = ArbitrationEngine(store)
                d = engine.propose({"user": 1, "object": "cup", "region": "handle"})
                engine.confirm(d.proposal.menu_id, "PINCH", "persist")
                engine.finish("persist", "accepted")
                old_id = d.proposal.menu_id
            with PreferenceStore(db) as store:
                engine = ArbitrationEngine(store)
                d = engine.propose({"user": 1, "object": "cup"})
                self.assertGreater(d.proposal.menu_id, old_id)
                self.assertEqual(d.proposal.items[0], Grip.PINCH)
                engine.confirm(old_id, "PINCH", "persist")
                self.assertEqual(store.counts("1", "cup"), {"PINCH": 1})

    def test_simulator_loads_real_menu_and_does_not_auto_execute(self):
        app = ArbitrationSimApp(self.engine, ArbitrationInput(1, "cup", "handle"))
        self.assertEqual(app.fsm.state, FsmState.ADAPTIVE)
        self.assertIsNone(app.fsm.active_grip)
        self.assertEqual(app.fsm.progress, 0.0)
        app.key_down("1")
        self.assertEqual(app.request.region, "handle")
        app.key_down("e")
        app.key_up("e")
        app.key_down("1")
        self.assertEqual(app.request.region, "unknown")

    def test_simulator_continued_flexion_and_single_update(self):
        app = ArbitrationSimApp(self.engine, ArbitrationInput(1, "cup", "handle"))
        app.key_down("s")
        app.key_up("s")
        app.key_down("a")
        for _ in range(25):
            app.step(0.1)
        self.assertGreater(app.fsm.progress, 0.2)
        self.assertEqual(self.store.counts("1", "cup"), {"PINCH": 1})
        for _ in range(100):
            app.step(0.1)
        self.assertEqual(len(self.store.history()), 1)
        app.key_up("a")
        app.step(0.1)
        self.assertEqual(app.fsm.state, FsmState.HOLDING)

    def test_simulator_immediate_cancel_not_learned(self):
        app = ArbitrationSimApp(self.engine, ArbitrationInput(1, "cup", "handle"))
        app.key_down("a")
        app.step(0.1)
        app.key_up("a")
        app.key_down("e")
        app.key_up("e")
        app.step(0.1)
        self.assertEqual(self.store.history()[0]["status"], "cancelled")
        self.assertEqual(self.store.counts("1", "cup"), {})
        app.key_down("e")
        app.key_up("e")
        self.assertEqual(app.fsm.state, FsmState.HOME)
        app.key_down("m")
        self.assertEqual(app.fsm.state, FsmState.ADAPTIVE)


if __name__ == "__main__":
    unittest.main()
