"""Preference scoring and conservative menu-size policy."""

from dataclasses import dataclass
import math

from cavia.core.contracts import Grip, MenuPolicy


@dataclass(frozen=True)
class ArbitrationConfig:
    alpha: float = 1.0

    region_history_min: int = 3
    low_vision: float = 0.6

    shortcut_vision: float = 0.8
    shortcut_evidence: int = 5
    shortcut_share: float = 0.7
    shortcut_margin: float = 0.3

    def __post_init__(self) -> None:
        if (
            isinstance(self.alpha, bool)
            or not math.isfinite(self.alpha)
            or self.alpha <= 0
        ):
            raise ValueError("alpha must be finite and positive")

        for name in (
            "region_history_min",
            "shortcut_evidence",
        ):
            value = getattr(self, name)

            if type(value) is not int or value < 1:
                raise ValueError(
                    f"{name} must be a positive integer"
                )

        for name in (
            "low_vision",
            "shortcut_vision",
            "shortcut_share",
            "shortcut_margin",
        ):
            value = getattr(self, name)

            if (
                isinstance(value, bool)
                or not math.isfinite(value)
                or not 0 <= value <= 1
            ):
                raise ValueError(f"{name} must be in [0, 1]")

        if (
            self.shortcut_vision < self.low_vision
            or self.shortcut_evidence < self.region_history_min
        ):
            raise ValueError(
                "Shortcut gates cannot be weaker than normal gates"
            )


def rank_grips(
    grips: list[Grip],
    counts: dict[str, int],
    alpha: float,
) -> tuple[list[Grip], list[float], int]:
    """Rank compatible grips using smoothed selection counts."""

    evidence_n = sum(
        counts.get(grip.name, 0)
        for grip in grips
    )

    if not grips:
        return [], [], 0

    denominator = evidence_n + alpha * len(grips)

    scores = {
        grip: (
            counts.get(grip.name, 0) + alpha
        ) / denominator
        for grip in grips
    }

    # Stable sorting preserves default order when scores are tied.
    ranked = sorted(
        grips,
        key=lambda grip: scores[grip],
        reverse=True,
    )

    return (
        ranked,
        [scores[grip] for grip in ranked],
        evidence_n,
    )


def choose_policy(
    scores: list[float],
    region: str,
    vision: float | None,
    source: str,
    region_n: int,
    config: ArbitrationConfig,
) -> tuple[MenuPolicy, int, str]:
    """Return policy, number of visible grips and explanation."""

    size = len(scores)

    if size == 0:
        return (
            MenuPolicy.FULL_MENU,
            0,
            "no_compatible_candidates",
        )

    if size == 1:
        # One compatible option is not learned high confidence.
        return (
            MenuPolicy.FULL_COMPATIBLE,
            1,
            "single_compatible_grip",
        )

    if region == "unknown":
        return (
            MenuPolicy.FULL_COMPATIBLE,
            size,
            "object_menu_stays_complete",
        )

    if vision is None or vision < config.low_vision:
        return (
            MenuPolicy.FULL_COMPATIBLE,
            size,
            "missing_or_low_region_confidence",
        )

    if (
        source != "region"
        or region_n < config.region_history_min
    ):
        return (
            MenuPolicy.FULL_COMPATIBLE,
            size,
            "insufficient_region_history",
        )

    shortcut_allowed = (
        vision >= config.shortcut_vision
        and region_n >= config.shortcut_evidence
        and scores[0] >= config.shortcut_share
        and scores[0] - scores[1] >= config.shortcut_margin
    )

    if shortcut_allowed:
        return (
            MenuPolicy.ONE_CONFIRM,
            1,
            "strong_region_preference",
        )

    return (
        MenuPolicy.TOP_TWO,
        min(2, size),
        "region_history_available",
    )