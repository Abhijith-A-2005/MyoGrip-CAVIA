"""Vision/dashboard context to ranked adaptive menu."""

from __future__ import annotations

import time
from typing import Any, Iterable

from cavia.core.contracts import (
    Condition,
    Grip,
    MenuConfidence,
    MenuContext,
    MenuProposal,
)
from cavia.core.grips import full_menu

from .candidates import candidates
from .contracts import ArbitrationInput, MenuDecision
from .menu_policy import (
    ArbitrationConfig,
    choose_policy,
    rank_grips,
)
from .preferences import PreferenceStore


class ArbitrationEngine:
    def __init__(
        self,
        store: PreferenceStore,
        *,
        config: ArbitrationConfig | None = None,
        available_grips: Iterable[Grip] | None = None,
    ):
        self.store = store
        self.config = config or ArbitrationConfig()

        # Existing grip-library flags are simulation defaults
        # until physical calibration is verified.
        self.available = tuple(
            full_menu()
            if available_grips is None
            else available_grips
        )

        if (
            not self.available
            or any(
                not isinstance(grip, Grip)
                or grip is Grip.OPEN
                for grip in self.available
            )
            or len(set(self.available)) != len(self.available)
        ):
            raise ValueError(
                "available_grips must be non-empty, "
                "unique grasp Grip values"
            )

    def propose(
        self,
        request: ArbitrationInput | dict[str, Any],
    ) -> MenuDecision:
        if isinstance(request, dict):
            request = ArbitrationInput.from_dict(request)

        if not request.stable:
            raise ValueError(
                "Context is not stable; wait for vision to lock it"
            )

        grips, region = candidates(
            request.object,
            request.region,
            self.available,
        )

        # Includes accepted region and object-only selections.
        object_counts = self.store.counts(
            request.user,
            request.object,
        )

        region_counts = (
            self.store.counts(
                request.user,
                request.object,
                region,
            )
            if region != "unknown"
            else {}
        )

        region_n = sum(
            region_counts.get(grip.name, 0)
            for grip in grips
        )

        # Use region-specific evidence when sufficient.
        # Otherwise fall back to the object's aggregate history.
        if (
            region != "unknown"
            and region_n >= self.config.region_history_min
        ):
            counts = region_counts
            source = "region"

        elif sum(
            object_counts.get(grip.name, 0)
            for grip in grips
        ):
            counts = object_counts
            source = "object"

        else:
            counts = {}
            source = "default"

        ranked, scores, evidence_n = rank_grips(
            grips,
            counts,
            self.config.alpha,
        )

        vision = (
            request.vision_confidence
            if region != "unknown"
            else None
        )

        policy, size, reason = choose_policy(
            scores,
            region,
            vision,
            source,
            region_n,
            self.config,
        )

        proposal = MenuProposal(
            ts=time.monotonic(),
            menu_id=0,
            condition=Condition.C3_ADAPTIVE,
            context=MenuContext(
                request.object,
                region,
                vision or 0.0,
            ),
            policy=policy,
            items=ranked[:size],
            scores=scores[:size],
            confidence=MenuConfidence(
                vision=vision or 0.0,
                evidence_n=evidence_n,
                top_share=scores[0] if scores else 0.0,
                margin=(
                    scores[0] - scores[1]
                    if len(scores) > 1
                    else 0.0
                ),
            ),
            full_menu=list(self.available),
        )

        decision = MenuDecision(
            user=request.user,
            proposal=proposal,
            compatible=tuple(
                grip.name for grip in ranked
            ),
            ranking_source=source,
            region_evidence_n=region_n,
            reason=reason,
            requested_region=request.region,
        )

        proposal.menu_id = self.store.save_menu(
            decision.to_dict()
        )

        return decision

    def confirm(
        self,
        menu_id: int,
        grip: str | Grip,
        interaction_id: str,
        *,
        from_full_menu: bool = False,
        instructed: bool = False,
    ) -> dict[str, Any]:
        name = (
            grip.name
            if isinstance(grip, Grip)
            else grip
        )

        return self.store.record_confirmation(
            menu_id,
            name,
            interaction_id,
            from_full_menu=from_full_menu,
            instructed=instructed,
        )

    def finish(
        self,
        interaction_id: str,
        outcome: str,
        *,
        grasp_success: bool | None = None,
    ) -> dict[str, Any]:
        return self.store.finish(
            interaction_id,
            outcome,
            grasp_success=grasp_success,
        )