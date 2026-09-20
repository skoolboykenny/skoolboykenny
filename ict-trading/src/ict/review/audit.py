"""The check that decides whether the review layer keeps its job.

From the record: "Every decision, including skipped ones, is logged. If skipped
trades would have won more than they lost, the AI layer is switched off."

That sentence is the only thing standing between a review layer and an
expensive superstition. A filter that blocks trades feels useful because the
blocked losers are memorable and the blocked winners are invisible. This module
makes them visible, by recording what the strategy would have done and scoring
the counterfactual.

**Counterfactuals are not free.** What a skipped trade would have done can only
be known by simulating it, and a simulation is exactly as good as the engine
that produces it. The number here is an estimate from the same backtest
machinery, with the same pessimism, and it is worth having for the sign rather
than the magnitude: a layer blocking +8R of winners is wrong whatever the
decimal place.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from .types import ReviewRequest, Verdict


@dataclass
class Decision:
    """One review, and what the trade went on to do.

    ``outcome_r`` is filled in later: at review time nobody knows, and a field
    that is empty until the trade resolves is more honest than one holding a
    guess.
    """

    at: pd.Timestamp
    instrument: str
    model: str
    direction: str
    entry: float
    stop: float
    target: float
    reward_to_risk: float
    action: str
    size_multiple: float
    reason: str
    reviewer: str
    outcome_r: float | None = None
    counterfactual: bool = False

    @classmethod
    def of(cls, request: ReviewRequest, verdict: Verdict) -> "Decision":
        return cls(
            at=request.at,
            instrument=request.instrument,
            model=request.model,
            direction=request.direction,
            entry=request.entry,
            stop=request.stop,
            target=request.target,
            reward_to_risk=request.reward_to_risk,
            action=verdict.action,
            size_multiple=verdict.size_multiple,
            reason=verdict.reason,
            reviewer=verdict.reviewer,
            counterfactual=verdict.blocks,
        )


@dataclass
class Journal:
    """Every decision the layer made, taken and skipped alike.

    The skipped ones are the whole point. A journal of trades taken cannot
    answer the only question worth asking about a filter.
    """

    decisions: list[Decision] = field(default_factory=list)

    def record(self, request: ReviewRequest, verdict: Verdict) -> Decision:
        decision = Decision.of(request, verdict)
        self.decisions.append(decision)
        return decision

    def settle(self, at: pd.Timestamp, outcome_r: float) -> None:
        """Attach a result to the decision made at ``at``."""
        for decision in reversed(self.decisions):
            if decision.at == at and decision.outcome_r is None:
                decision.outcome_r = outcome_r
                return

    def to_frame(self) -> pd.DataFrame:
        if not self.decisions:
            return pd.DataFrame(
                columns=[
                    "at", "instrument", "model", "direction", "entry", "stop",
                    "target", "reward_to_risk", "action", "size_multiple",
                    "reason", "reviewer", "outcome_r", "counterfactual",
                ]
            )
        return pd.DataFrame([d.__dict__ for d in self.decisions])

    def write_csv(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.to_frame().to_csv(path, index=False)
        return path


@dataclass
class Audit:
    """What the layer cost or saved, and whether it should stay on."""

    reviewed: int
    taken: int
    reduced: int
    skipped: int
    skipped_r: float
    reduced_r_forgone: float
    taken_r: float
    unsettled: int = 0

    @property
    def net_effect_r(self) -> float:
        """R the layer gave up. Negative means it saved money.

        Positive is the bad direction: it means the trades the layer blocked
        or shrank would have made more than they lost.
        """
        return self.skipped_r + self.reduced_r_forgone

    @property
    def should_switch_off(self) -> bool:
        """The record's rule, applied literally."""
        return self.net_effect_r > 0

    @property
    def has_enough_evidence(self) -> bool:
        """Twenty blocked trades before the verdict means anything.

        A layer that skipped three trades has not been tested, whichever way
        those three went.
        """
        return (self.skipped + self.reduced) >= 20

    def summary(self) -> str:
        lines = [
            "Review layer audit",
            "=" * 66,
            f"reviewed            {self.reviewed}",
            f"  taken             {self.taken}",
            f"  reduced           {self.reduced}",
            f"  skipped           {self.skipped}",
            "",
            f"R from trades taken             {self.taken_r:+.2f}",
            f"R the skipped trades would have {self.skipped_r:+.2f}",
            f"R given up by reducing          {self.reduced_r_forgone:+.2f}",
            f"net effect of the layer         {self.net_effect_r:+.2f}R",
        ]
        if self.unsettled:
            lines.append(
                f"\n{self.unsettled} decisions have no outcome yet and are excluded."
            )

        lines.append("")
        if not self.has_enough_evidence:
            lines.append(
                f"Only {self.skipped + self.reduced} trades were blocked or "
                "shrunk, which is too few to judge the layer either way."
            )
        elif self.should_switch_off:
            lines.append(
                f"SWITCH THE LAYER OFF. It gave up {self.net_effect_r:+.2f}R: "
                "the trades it blocked would have won more than they lost."
            )
        else:
            lines.append(
                f"The layer saved {-self.net_effect_r:.2f}R. Keep it, and audit "
                "it again after the next hundred decisions."
            )
        return "\n".join(lines)


def audit(journal: Journal) -> Audit:
    """Score a journal once the outcomes are in."""
    frame = journal.to_frame()
    if frame.empty:
        return Audit(0, 0, 0, 0, 0.0, 0.0, 0.0)

    settled = frame.loc[frame["outcome_r"].notna()]
    unsettled = len(frame) - len(settled)

    skipped = settled.loc[settled["action"] == "skip"]
    reduced = settled.loc[settled["action"] == "reduce"]
    taken = settled.loc[settled["action"] == "take"]

    # A reduced trade gave up the share of R it was not sized for.
    forgone = (reduced["outcome_r"] * (1.0 - reduced["size_multiple"])).sum()

    return Audit(
        reviewed=len(frame),
        taken=int((frame["action"] == "take").sum()),
        reduced=int((frame["action"] == "reduce").sum()),
        skipped=int((frame["action"] == "skip").sum()),
        skipped_r=float(skipped["outcome_r"].sum()),
        reduced_r_forgone=float(forgone),
        taken_r=float((taken["outcome_r"] * taken["size_multiple"]).sum()),
        unsettled=unsettled,
    )
