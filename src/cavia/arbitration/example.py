"""Synthetic walkthrough using an in-memory database."""

import json

from .engine import ArbitrationEngine
from .preferences import PreferenceStore


def main() -> None:
    with PreferenceStore(":memory:") as store:
        engine = ArbitrationEngine(store)

        def show(
            region: str,
            user: str = "1",
        ) -> None:
            decision = engine.propose({
                "user": user,
                "object": "cup",
                "region": region,
                "vision_confidence": 0.9,
            })

            print(json.dumps({
                "user": user,
                "region": region,
                "items": decision.proposal.to_dict()["items"],
                "policy": decision.proposal.policy.value,
                "source": decision.ranking_source,
                "evidence_n": (
                    decision.proposal.confidence.evidence_n
                ),
            }))

        print("Cold start — all inputs here are synthetic:")
        show("unknown")

        # Simulate eight accepted handle/pinch interactions.
        for index in range(8):
            menu = engine.propose({
                "user": 1,
                "object": "cup",
                "region": "handle",
            })

            interaction_id = f"mock-handle-{index}"

            engine.confirm(
                menu.proposal.menu_id,
                "PINCH",
                interaction_id,
                from_full_menu=True,
            )

            engine.finish(
                interaction_id,
                "accepted",
            )

        # Simulate three accepted body/power interactions.
        for index in range(3):
            menu = engine.propose({
                "user": 1,
                "object": "cup",
                "region": "body",
            })

            interaction_id = f"mock-body-{index}"

            engine.confirm(
                menu.proposal.menu_id,
                "POWER",
                interaction_id,
                from_full_menu=True,
            )

            engine.finish(
                interaction_id,
                "accepted",
            )

        print(
            "\nAfter 8 handle/pinch and 3 body/power selections:"
        )

        show("unknown")
        show("handle")
        show("body")

        print("\nA different user still has no history:")
        show("unknown", "2")


if __name__ == "__main__":
    main()
