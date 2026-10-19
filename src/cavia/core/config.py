"""Tunable parameters. Values are ASSUMPTIONS until calibrated (see docs/architecture.md)."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any


@dataclass
class FsmConfig:
    # grip_progress units per second (0.0 = open, 1.0 = calibrated full closure).
    close_speed: float = 0.25
    open_speed: float = 0.35
    # Controlled opening after HE during actuation.
    he_return_speed: float = 0.5


@dataclass
class PolicyConfig:
    low_vision: float = 0.6          # below: FULL_COMPATIBLE
    min_evidence: int = 3            # below: FULL_COMPATIBLE (cold start)
    shortcut_vision: float = 0.8     # ONE_CONFIRM needs all four shortcut_* / min_* gates
    shortcut_evidence: int = 5
    shortcut_top_share: float = 0.7
    shortcut_margin: float = 0.3
    smoothing_alpha: float = 1.0


@dataclass
class CaviaConfig:
    fsm: FsmConfig = field(default_factory=FsmConfig)
    policy: PolicyConfig = field(default_factory=PolicyConfig)


def _apply(target: Any, values: dict[str, Any]) -> None:
    known = {f.name for f in fields(target)}
    for key, value in values.items():
        if key not in known:
            raise KeyError(f"Unknown config key {type(target).__name__}.{key}")
        setattr(target, key, value)


def load_config(path: str | Path | None = None) -> CaviaConfig:
    """Defaults, optionally overridden by a TOML file with [fsm] and [policy] tables."""
    cfg = CaviaConfig()
    if path is None:
        return cfg
    with open(path, "rb") as f:
        data = tomllib.load(f)
    _apply(cfg.fsm, data.get("fsm", {}))
    _apply(cfg.policy, data.get("policy", {}))
    return cfg
