"""What the review layer may receive and what it may return.

The record sets one hard constraint: the AI layer "can only make a trade
smaller or cancel it, never larger or earlier". That is enforced here, in the
type, not in the caller and not in the prompt. A model that returns a size
multiple of 3 gets clamped to 1; a model that returns "take" on a setup the
risk checks already rejected never sees the setup at all.

The reason for putting it here rather than trusting the prompt is that the
input is not trusted. Headlines come from the internet and go into a language
model, so anything in them that reads like an instruction is a possible
injection. The clamp means the worst a successful injection can do is skip a
trade the strategy wanted, which is a bad day rather than a blown account.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

#: The only three answers the layer may give.
ACTIONS = ("take", "reduce", "skip")


@dataclass(frozen=True)
class Verdict:
    """The review layer's answer, already clamped to what it is allowed to do.

    ``size_multiple`` is applied to the size the risk manager calculated. It is
    clamped into ``[0, 1]`` on construction, so no verdict from any source,
    model, file or attacker, can enlarge a position.
    """

    action: str
    size_multiple: float
    reason: str
    reviewer: str = ""
    at: pd.Timestamp | None = None

    def __post_init__(self) -> None:
        original = self.action
        action = str(self.action).strip().lower()
        if action not in ACTIONS:
            # An unparseable answer is a skip, not a take. The layer failing
            # open would make it a source of trades, which it must never be.
            object.__setattr__(self, "action", "skip")
            object.__setattr__(self, "size_multiple", 0.0)
            object.__setattr__(
                self, "reason", f"unrecognised action {original!r}, treated as skip"
            )
            return

        object.__setattr__(self, "action", action)
        multiple = self.size_multiple
        try:
            multiple = float(multiple)
        except (TypeError, ValueError):
            multiple = 0.0
        if multiple != multiple:  # NaN
            multiple = 0.0

        if action == "skip":
            multiple = 0.0
        elif action == "take":
            multiple = 1.0
        else:
            # The only case with a free number, and the only one that needs
            # clamping. Above 1 is refused rather than honoured.
            multiple = min(max(multiple, 0.0), 1.0)
        object.__setattr__(self, "size_multiple", multiple)

    @property
    def blocks(self) -> bool:
        return self.size_multiple <= 0.0

    @classmethod
    def take(cls, reason: str = "", reviewer: str = "") -> "Verdict":
        return cls("take", 1.0, reason or "no objection", reviewer)

    @classmethod
    def skip(cls, reason: str, reviewer: str = "") -> "Verdict":
        return cls("skip", 0.0, reason, reviewer)

    @classmethod
    def reduce(cls, size_multiple: float, reason: str, reviewer: str = "") -> "Verdict":
        return cls("reduce", size_multiple, reason, reviewer)

    def __str__(self) -> str:
        if self.action == "reduce":
            return f"reduce to {self.size_multiple:.0%}: {self.reason}"
        return f"{self.action}: {self.reason}"


@dataclass
class ReviewRequest:
    """Structured facts about one setup. Never a chart image.

    The record is explicit that the layer "receives structured data, not a raw
    chart", because language models are poor at reading exact price levels from
    images and will confidently invent one.
    """

    instrument: str
    at: pd.Timestamp
    direction: str
    entry: float
    stop: float
    target: float
    reward_to_risk: float
    model: str
    reason: str
    session: str = ""
    daily_bias: str = ""
    timeframe_alignment: str = ""
    confluence: list[str] = field(default_factory=list)
    upcoming_events: list[str] = field(default_factory=list)
    headlines: list[str] = field(default_factory=list)
    recent_performance: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        """The payload a reviewer sees. JSON safe, and entirely structured."""
        return {
            "instrument": self.instrument,
            "time_utc": str(self.at),
            "direction": self.direction,
            "entry": round(self.entry, 5),
            "stop": round(self.stop, 5),
            "target": round(self.target, 5),
            "reward_to_risk": round(self.reward_to_risk, 2),
            "model": self.model,
            "setup_reason": self.reason,
            "session": self.session,
            "daily_bias": self.daily_bias,
            "timeframe_alignment": self.timeframe_alignment,
            "confluence": list(self.confluence),
            "upcoming_events": list(self.upcoming_events),
            "headlines": list(self.headlines),
            "recent_performance": dict(self.recent_performance),
        }
