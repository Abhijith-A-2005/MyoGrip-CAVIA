"""Grip library. Only grips calibrated on the real hand may appear in any menu."""

from __future__ import annotations

from dataclasses import dataclass

from cavia.core.contracts import Grip


@dataclass(frozen=True)
class GripSpec:
    grip: Grip
    label: str
    calibrated: bool


# Flip `calibrated` to False for any grip that fails bench calibration.
GRIP_LIBRARY: dict[Grip, GripSpec] = {
    Grip.OPEN: GripSpec(Grip.OPEN, "Open", True),
    Grip.POWER: GripSpec(Grip.POWER, "Power / Cylindrical", True),
    Grip.PINCH: GripSpec(Grip.PINCH, "Pinch", True),
    Grip.TRIPOD: GripSpec(Grip.TRIPOD, "Tripod", True),
    Grip.LATERAL: GripSpec(Grip.LATERAL, "Lateral / Support", True),
}


def is_calibrated(grip: Grip) -> bool:
    return GRIP_LIBRARY[grip].calibrated


def full_menu() -> list[Grip]:
    """All calibrated grasp grips in fixed order (OPEN is a hand state, not a menu choice)."""
    return [g for g, spec in GRIP_LIBRARY.items() if spec.calibrated and g is not Grip.OPEN]
