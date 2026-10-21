"""Arbitration records; existing core contracts remain unchanged."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

from cavia.core.contracts import MenuProposal


def normalize_name(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Object and region names must be non-empty strings")

    return " ".join(
        value.strip().lower().replace("_", " ").split()
    )


def user_key(value: str | int) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError("user must be a non-empty string or integer")

    result = str(value).strip()

    if not result:
        raise ValueError("user cannot be empty")

    return result


@dataclass(frozen=True)
class ArbitrationInput:
    user: str | int
    object: str
    region: str | None = "unknown"

    # Validated REGION confidence, not detector confidence alone.
    vision_confidence: float | None = None

    # The caller supplies a locked context.
    stable: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "user", user_key(self.user))

        name = normalize_name(self.object)
        name = {
            "mug": "cup",
            "phone": "cell phone",
        }.get(name, name)

        object.__setattr__(self, "object", name)

        region = (
            "unknown"
            if self.region is None
            else normalize_name(self.region)
        )

        object.__setattr__(
            self, "region", region.replace(" ", "_")
        )

        if type(self.stable) is not bool:
            raise ValueError("stable must be a boolean")

        if self.vision_confidence is not None:
            value = self.vision_confidence

            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or not 0 <= value <= 1
            ):
                raise ValueError(
                    "vision_confidence must be finite and between 0 and 1"
                )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ArbitrationInput:
        return cls(**data)


@dataclass(frozen=True)
class MenuDecision:
    user: str
    proposal: MenuProposal

    # Complete ranked compatible set, before menu reduction.
    compatible: tuple[str, ...]

    ranking_source: str
    region_evidence_n: int
    reason: str
    requested_region: str

    def to_dict(self) -> dict[str, Any]:
        result = self.proposal.to_dict()

        result.update(
            user=self.user,
            compatible=list(self.compatible),
            ranking_source=self.ranking_source,
            region_evidence_n=self.region_evidence_n,
            reason=self.reason,
            requested_region=self.requested_region,
        )

        return result