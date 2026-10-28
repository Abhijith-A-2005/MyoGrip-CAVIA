"""Configured object/region compatibility rules.

These mappings require physical validation.
"""

from cavia.core.contracts import Grip


P = Grip.POWER
I = Grip.PINCH
T = Grip.TRIPOD
L = Grip.LATERAL


REGION_GRIPS: dict[str, dict[str, tuple[Grip, ...]]] = {
    "cup": {
        "body": (P, L),
        "handle": (L, I),
    },
    "bottle": {
        "body": (P, T),
        "cap": (T, I),
    },
    "toothbrush": {
        "handle": (T, L, I),
        "shank": (I, T),
    },
    "spoon": {
        "handle": (L, T),
    },
    "cell phone": {
        "side_edge": (L, I),
        "lower_support": (P, L),
    },
    "remote": {
        "side_edge": (L, I),
        "lower_support": (P, L),
    },
    "book": {
        "side_edge": (L, I),
        "cover_face": (P,),
    },
}


def candidates(
    object_name: str,
    region: str,
    available: tuple[Grip, ...],
) -> tuple[list[Grip], str]:
    """Return compatible grips and the effective region."""

    regions = REGION_GRIPS.get(object_name)

    if regions is None:
        return [], "unknown"

    effective_region = (
        region if region in regions else "unknown"
    )

    if effective_region == "unknown":
        # Object-level menu: union of its known region candidates.
        # dict.fromkeys removes duplicates while preserving order.
        configured = dict.fromkeys(
            grip
            for grips in regions.values()
            for grip in grips
        )
    else:
        configured = dict.fromkeys(
            regions[effective_region]
        )

    filtered = [
        grip
        for grip in configured
        if grip in available
    ]

    return filtered, effective_region