"""Message contracts shared across CAVIA modules. Mirrors docs/interfaces.md."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum, IntEnum
from typing import Any


class Grip(IntEnum):
    # Wire values sent to the NPG firmware; never renumber.
    OPEN = 0
    POWER = 1
    PINCH = 2
    TRIPOD = 3
    LATERAL = 4


class VisionState(str, Enum):
    NO_OBJECT = "NO_OBJECT"
    SEARCHING = "SEARCHING"
    LOCKED = "LOCKED"
    LOST = "LOST"


class EmgEvent(str, Enum):
    SF = "SF"
    SE = "SE"
    LF = "LF"
    LE = "LE"
    HE = "HE"
    REST = "REST"
    INVALID = "INVALID"


class Activity(str, Enum):
    REST = "REST"
    FLEX_ACTIVE = "FLEX_ACTIVE"
    EXT_ACTIVE = "EXT_ACTIVE"
    INVALID = "INVALID"


class FsmState(str, Enum):
    HOME = "HOME"
    ADAPTIVE = "ADAPTIVE"
    FULL = "FULL"
    CLOSING = "CLOSING"
    HOLDING = "HOLDING"
    OPENING = "OPENING"


class MenuKind(str, Enum):
    ADAPTIVE = "ADAPTIVE"
    FULL = "FULL"


class MenuPolicy(str, Enum):
    FULL_COMPATIBLE = "FULL_COMPATIBLE"
    TOP_TWO = "TOP_TWO"
    ONE_CONFIRM = "ONE_CONFIRM"
    FULL_MENU = "FULL_MENU"


class Condition(str, Enum):
    C1_MANUAL = "C1_MANUAL"
    C2_STATIC = "C2_STATIC"
    C3_ADAPTIVE = "C3_ADAPTIVE"


def _grip_names(grips: list[Grip]) -> list[str]:
    return [g.name for g in grips]


def _grips(names: list[str]) -> list[Grip]:
    return [Grip[n] for n in names]


def _opt_grip(name: str | None) -> Grip | None:
    return None if name is None else Grip[name]


@dataclass
class VisionResult:
    ts: float
    frame_seq: int
    state: VisionState
    object: str | None = None
    region: str | None = None
    region_confidence: float = 0.0
    det_conf: float = 0.0
    reticle_score: float = 0.0
    stability: float = 0.0
    stable: bool = False

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["state"] = self.state.value
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> VisionResult:
        return cls(**{**d, "state": VisionState(d["state"])})


@dataclass
class MenuContext:
    object: str | None
    region: str | None
    region_confidence: float = 0.0


@dataclass
class MenuConfidence:
    vision: float = 0.0
    evidence_n: int = 0
    top_share: float = 0.0
    margin: float = 0.0


@dataclass
class MenuProposal:
    ts: float
    menu_id: int
    condition: Condition
    context: MenuContext
    policy: MenuPolicy
    items: list[Grip]
    scores: list[float]
    confidence: MenuConfidence
    full_menu: list[Grip]

    def __post_init__(self) -> None:
        # An invalid menu must fail where it is built, not as a crash inside the FSM.
        if not self.full_menu:
            raise ValueError("full_menu must contain at least one calibrated grip")
        if len(self.scores) != len(self.items):
            raise ValueError("scores must have one entry per item")
        for name, grips in (("items", self.items), ("full_menu", self.full_menu)):
            if Grip.OPEN in grips:
                raise ValueError(f"OPEN is a hand state, not a menu choice ({name})")
            if len(set(grips)) != len(grips):
                raise ValueError(f"duplicate grips in {name}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "ts": self.ts,
            "menu_id": self.menu_id,
            "condition": self.condition.value,
            "context": asdict(self.context),
            "policy": self.policy.value,
            "items": _grip_names(self.items),
            "scores": list(self.scores),
            "confidence": asdict(self.confidence),
            "full_menu": _grip_names(self.full_menu),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> MenuProposal:
        return cls(
            ts=d["ts"],
            menu_id=d["menu_id"],
            condition=Condition(d["condition"]),
            context=MenuContext(**d["context"]),
            policy=MenuPolicy(d["policy"]),
            items=_grips(d["items"]),
            scores=list(d["scores"]),
            confidence=MenuConfidence(**d["confidence"]),
            full_menu=_grips(d["full_menu"]),
        )


@dataclass
class EmgInput:
    """Exactly one of `event` (menu mode) or `activity` (actuation mode) is set."""

    ts: float
    source: str  # "device" | "keyboard" | "replay"
    event: EmgEvent | None = None
    activity: Activity | None = None

    def __post_init__(self) -> None:
        if (self.event is None) == (self.activity is None):
            raise ValueError("EmgInput needs exactly one of event or activity")

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"ts": self.ts, "source": self.source}
        if self.event is not None:
            d["event"] = self.event.value
        else:
            d["activity"] = self.activity.value
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> EmgInput:
        return cls(
            ts=d["ts"],
            source=d["source"],
            event=EmgEvent(d["event"]) if "event" in d else None,
            activity=Activity(d["activity"]) if "activity" in d else None,
        )


@dataclass
class FsmStatus:
    ts: float
    menu_id: int | None
    state: FsmState
    menu_kind: MenuKind | None
    selected_index: int
    selected_grip: Grip | None
    active_grip: Grip | None
    grip_progress: float
    wait_release: bool
    last_event: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ts": self.ts,
            "menu_id": self.menu_id,
            "state": self.state.value,
            "menu_kind": None if self.menu_kind is None else self.menu_kind.value,
            "selected_index": self.selected_index,
            "selected_grip": None if self.selected_grip is None else self.selected_grip.name,
            "active_grip": None if self.active_grip is None else self.active_grip.name,
            "grip_progress": round(self.grip_progress, 4),
            "wait_release": self.wait_release,
            "last_event": self.last_event,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> FsmStatus:
        return cls(
            ts=d["ts"],
            menu_id=d["menu_id"],
            state=FsmState(d["state"]),
            menu_kind=None if d["menu_kind"] is None else MenuKind(d["menu_kind"]),
            selected_index=d["selected_index"],
            selected_grip=_opt_grip(d["selected_grip"]),
            active_grip=_opt_grip(d["active_grip"]),
            grip_progress=d["grip_progress"],
            wait_release=d["wait_release"],
            last_event=d.get("last_event"),
        )


LOG_TYPES = frozenset({
    "session_start", "trial_start", "vision", "menu", "emg",
    "fsm", "preference_update", "trial_end", "note",
})


@dataclass
class LogRecord:
    wall: float
    ts: float
    session: str
    user: str
    condition: Condition
    trial: int | None
    type: str
    data: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.type not in LOG_TYPES:
            raise ValueError(f"Unknown log record type: {self.type}")

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["condition"] = self.condition.value
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> LogRecord:
        return cls(**{**d, "condition": Condition(d["condition"])})
