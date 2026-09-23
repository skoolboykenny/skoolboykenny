"""Scoring hand labels against the detectors.

Phase 1's gate is that a detector agrees with hand marked charts at least 90%
of the time. Exporting charts is only half of that: without a way to record
marks and score them, "90%" is a number nobody can actually check.

The flow is:

1. ``ict sample`` writes charts and a blank ``labels.csv``.
2. You open each chart and add a row per concept you can see, by hand.
3. ``ict verify`` runs the detectors over the same days and scores them.

A label matches a detection when they name the same concept on the same day
and sit within a few candles of each other. Time is the anchor rather than
price, because reading a timestamp off a chart is reliable and reading an exact
price off one is not.

Three numbers are reported per concept:

``recall``
    Of what you marked, how much the detector found. Low recall means it is
    blind to something you can see.
``precision``
    Of what the detector found, how much you marked. Low precision means it is
    inventing structure, which is the more dangerous failure: those become
    trades.
``agreement``
    Matched labels over everything either side claimed, matches included once.
    This is the number the 90% gate is read against, because it punishes both
    failures at once.

Agreement is stricter than reading recall alone, and deliberately so. Ten marks
against ten detections with nine matched is one miss and one invention: recall
and precision are both 0.90, but agreement is 9 / 11 = 0.82 and the gate fails.
Clearing 90% means being near perfect in both directions, which is the point.
A detector that is merely mostly right becomes a backtest that is confidently
wrong.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .analysis import Analysis

#: Concepts a person can reasonably mark on a chart, and where to find them
#: in an :class:`~ict.analysis.Analysis`.
CONCEPTS: dict[str, str] = {
    "swing_high": "swings",
    "swing_low": "swings",
    "sweep": "sweeps",
    "mss": "shifts",
    "fvg": "fvgs",
    "order_block": "order_blocks",
}

LABEL_COLUMNS = ("date", "timeframe", "concept", "time", "note")

#: How far apart a label and a detection may sit and still be the same event.
#: Two candles allows for reading a timestamp off a chart by eye.
DEFAULT_TOLERANCE_CANDLES = 2

#: The gate from the Phase 1 brief.
PASS_THRESHOLD = 0.90


@dataclass(frozen=True)
class ConceptScore:
    """How one concept scored against the labels."""

    concept: str
    labelled: int
    detected: int
    matched: int

    @property
    def recall(self) -> float:
        return self.matched / self.labelled if self.labelled else float("nan")

    @property
    def precision(self) -> float:
        return self.matched / self.detected if self.detected else float("nan")

    @property
    def agreement(self) -> float:
        """Matched over everything either side claimed."""
        claimed = self.labelled + self.detected - self.matched
        return self.matched / claimed if claimed else float("nan")

    @property
    def passes(self) -> bool:
        agreement = self.agreement
        return agreement == agreement and agreement >= PASS_THRESHOLD


def blank_labels() -> pd.DataFrame:
    """An empty labels frame, for `ict sample` to write as a template."""
    return pd.DataFrame({column: pd.Series(dtype="object") for column in LABEL_COLUMNS})


def read_labels(path: str) -> pd.DataFrame:
    """Read a hand filled labels file.

    ``time`` is read as New York wall clock, because that is what the charts
    are drawn on, and converted to UTC to match the detectors.
    """
    frame = pd.read_csv(path)
    missing = set(LABEL_COLUMNS) - set(frame.columns) - {"note"}
    if missing:
        raise ValueError(f"labels file is missing columns: {sorted(missing)}")

    frame = frame.loc[frame["concept"].notna() & frame["time"].notna()].copy()
    if frame.empty:
        return frame

    unknown = set(frame["concept"]) - set(CONCEPTS)
    if unknown:
        raise ValueError(
            f"unknown concepts in labels: {sorted(unknown)}. "
            f"Expected one of {sorted(CONCEPTS)}."
        )

    stamps = pd.to_datetime(frame["time"], format="mixed")
    if stamps.dt.tz is None:
        stamps = stamps.dt.tz_localize("America/New_York", ambiguous=True)
    frame["time_utc"] = stamps.dt.tz_convert("UTC")
    return frame.reset_index(drop=True)


def detections(analysis: Analysis, concept: str) -> pd.Series:
    """The timestamps the detector produced for one concept."""
    attribute = CONCEPTS[concept]
    frame = getattr(analysis, attribute)
    if frame.empty:
        return pd.Series(dtype="datetime64[ns, UTC]")

    if concept in ("swing_high", "swing_low"):
        kind = "high" if concept == "swing_high" else "low"
        frame = frame.loc[frame["kind"] == kind]

    return pd.Series(frame["time"].to_numpy(), dtype="datetime64[ns, UTC]")


def score_concept(
    concept: str,
    labelled: pd.Series,
    detected: pd.Series,
    tolerance: pd.Timedelta,
) -> ConceptScore:
    """Match labels to detections greedily, nearest first.

    Each label may claim at most one detection and vice versa, so a detector
    that fires ten times around one marked event scores one match and nine
    false positives rather than ten matches.
    """
    remaining = list(detected.sort_values())
    matched = 0

    for stamp in labelled.sort_values():
        best = None
        best_gap = tolerance
        for candidate in remaining:
            gap = abs(candidate - stamp)
            if gap <= best_gap:
                best, best_gap = candidate, gap
        if best is not None:
            remaining.remove(best)
            matched += 1

    return ConceptScore(
        concept=concept,
        labelled=len(labelled),
        detected=len(detected),
        matched=matched,
    )


def score(
    labels: pd.DataFrame,
    analyses: dict[tuple[str, str], Analysis],
    tolerance: pd.Timedelta,
    reviewed: set[tuple[str, str]] | None = None,
) -> list[ConceptScore]:
    """Score every concept that appears in the labels.

    ``analyses`` is keyed by ``(date, timeframe)``, matching the labels file,
    so a day marked on the 15 minute chart is scored against the 15 minute
    detectors rather than the 1 minute ones.

    ``reviewed`` is every chart a person actually looked at, and leaving it out
    hides the failure this gate exists to catch.

    Without it, only charts carrying at least one label of a concept are
    scored. A chart where the person correctly saw nothing contributes no
    labels, so it is skipped, and every false positive the detector fired there
    becomes invisible. A detector that over-fires on exactly the quiet days
    would pass a gate built to fail it. With ``reviewed``, a chart that was
    looked at counts its detections whether or not anything was marked on it.
    """
    scores: list[ConceptScore] = []
    charts = set(reviewed) if reviewed else None

    for concept in sorted(set(labels["concept"])):
        rows = labels.loc[labels["concept"] == concept]
        labelled_times: list[pd.Timestamp] = []
        detected_times: list[pd.Timestamp] = []

        by_chart = {
            (str(day), str(timeframe)): group
            for (day, timeframe), group in rows.groupby(["date", "timeframe"])
        }
        for key in sorted(charts if charts is not None else by_chart):
            analysis = analyses.get(key)
            if analysis is None:
                continue
            group = by_chart.get(key)
            if group is not None:
                labelled_times.extend(group["time_utc"].tolist())
            detected_times.extend(detections(analysis, concept).tolist())

        scores.append(
            score_concept(
                concept,
                pd.Series(labelled_times, dtype="datetime64[ns, UTC]"),
                pd.Series(detected_times, dtype="datetime64[ns, UTC]"),
                tolerance,
            )
        )

    return scores


def read_reviewed(path: str) -> set[tuple[str, str]]:
    """Read the charts a person marked as done, as ``(date, timeframe)``."""
    frame = pd.read_csv(path)
    missing = {"date", "timeframe"} - set(frame.columns)
    if missing:
        raise ValueError(f"{path} is missing columns: {sorted(missing)}")
    return {
        (str(row.date), str(row.timeframe))
        for row in frame.itertuples()
    }


def report(scores: list[ConceptScore]) -> str:
    """A table of the scores, with the gate applied."""
    if not scores:
        return "no labels to score"

    lines = [
        f"{'concept':<14}{'labelled':>9}{'detected':>9}{'matched':>9}"
        f"{'recall':>9}{'precision':>11}{'agreement':>11}  gate",
        "-" * 82,
    ]
    for item in scores:
        lines.append(
            f"{item.concept:<14}{item.labelled:>9}{item.detected:>9}"
            f"{item.matched:>9}{item.recall:>9.2f}{item.precision:>11.2f}"
            f"{item.agreement:>11.2f}  {'pass' if item.passes else 'FAIL'}"
        )

    failing = [s.concept for s in scores if not s.passes]
    lines.append("")
    if failing:
        lines.append(
            f"{len(failing)} of {len(scores)} concepts below the "
            f"{PASS_THRESHOLD:.0%} gate: {', '.join(failing)}"
        )
        lines.append("Those detectors are not ready to build a backtest on.")
    else:
        lines.append(f"every concept meets the {PASS_THRESHOLD:.0%} gate")
    return "\n".join(lines)
