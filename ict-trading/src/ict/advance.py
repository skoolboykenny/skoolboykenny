"""Work out what can be moved forward right now, and move it.

This is the module that lets the project run without a person in the loop for
the parts that do not need one. It looks at what is actually on disk, decides
which gate is next, and either runs it or says plainly who is blocking.

**It never adjusts anything to make a gate pass.** That is the whole risk of
running this unattended: an agent optimising for a green gate rather than for
the truth would tune thresholds until `ict verify` agreed with itself, and the
result would look like validation while being its opposite. So `advance` runs
gates and reports them. Changing a threshold because a gate failed is a
decision for a person looking at hand labels, and there is deliberately no code
path here that does it.

**It never places an order.** Nothing here calls the live loop, in either
environment. Paper trading starts when a person starts it.

**It never skips a gate.** The order in the project record is the order here,
and a gate that has not passed blocks the ones after it.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

#: Where each artefact is expected to live, relative to the project root.
DATA = Path("data/processed/eurusd_m1.parquet")
LABELS = Path("labels.csv")
REVIEWED = Path("reviewed.csv")
RESULTS = Path("results")

#: Commands `advance` is allowed to run. Anything that could place an order, or
#: change a parameter, is deliberately absent, and the runner refuses a step
#: whose command is not on this list.
ALLOWED = ("fetch", "gaps", "verify", "backtest", "rank", "robustness", "dashboard")


@dataclass
class State:
    """What exists right now."""

    has_token: bool = False
    environment: str = ""
    has_data: bool = False
    candles: int = 0
    span: str = ""
    has_labels: bool = False
    labelled_charts: int = 0
    has_reviewed: bool = False
    gate1: bool | None = None
    gate2: bool | None = None
    gate3: bool | None = None
    gate4: bool | None = None

    @property
    def gates(self) -> dict[str, bool | None]:
        return {
            "1 hand labels": self.gate1,
            "2 in sample": self.gate2,
            "3 walk forward": self.gate3,
            "4 robustness": self.gate4,
        }


@dataclass
class Step:
    """The next thing that can happen, and who has to do it."""

    name: str
    reason: str
    command: list[str] = field(default_factory=list)
    blocked_on_person: bool = False
    instructions: str = ""

    @property
    def is_mine(self) -> bool:
        return bool(self.command) and not self.blocked_on_person


def inspect(root: Path | None = None) -> State:
    """Read the world. No side effects."""
    root = Path(root or ".")
    state = State()

    state.has_token = bool(os.environ.get("OANDA_API_TOKEN", "").strip())
    state.environment = os.environ.get("OANDA_ENVIRONMENT", "").strip()

    data = root / DATA
    if data.exists():
        try:
            from .data.loader import read_parquet

            candles = read_parquet(data)
            state.has_data = not candles.empty
            state.candles = len(candles)
            if state.has_data:
                state.span = (
                    f"{candles.index[0]:%Y-%m-%d} to {candles.index[-1]:%Y-%m-%d}"
                )
        except Exception:
            state.has_data = False

    labels = root / LABELS
    if labels.exists():
        try:
            frame = pd.read_csv(labels)
            # The columns matter, not just that pandas read something. A half
            # written or unrelated CSV parses happily as one column and would
            # otherwise send an unattended run on to score junk as labels.
            needed = {"date", "timeframe", "concept", "time"}
            state.has_labels = not frame.empty and needed.issubset(frame.columns)
            if state.has_labels:
                state.labelled_charts = frame["date"].nunique()
        except Exception:
            state.has_labels = False

    state.has_reviewed = (root / REVIEWED).exists()

    for number in (1, 2, 3, 4):
        marker = root / RESULTS / f"gate{number}.passed"
        failed = root / RESULTS / f"gate{number}.failed"
        if marker.exists():
            setattr(state, f"gate{number}", True)
        elif failed.exists():
            setattr(state, f"gate{number}", False)

    return state


def next_step(state: State) -> Step:
    """The single next thing, in gate order. Never skips."""
    if not state.has_token:
        return Step(
            name="credentials",
            reason="No OANDA token in the environment, so no data can be fetched.",
            blocked_on_person=True,
            instructions=(
                "Open a free practice account at oanda.com, generate a token "
                "under Manage API Access, and add OANDA_API_TOKEN, "
                "OANDA_ACCOUNT_ID and OANDA_ENVIRONMENT=practice to the "
                "environment settings. Never paste the token into a chat. "
                "The network policy also has to allow api-fxpractice.oanda.com."
            ),
        )

    if not state.has_data:
        return Step(
            name="fetch",
            reason="Credentials are present and no history is stored yet.",
            command=["fetch", "--start", "2021-01-01", "--out", str(DATA)],
        )

    if state.gate1 is not True:
        if not state.has_labels:
            return Step(
                name="gate 1 labelling",
                reason=(
                    f"{state.candles:,} candles are stored ({state.span}) and "
                    "nothing has been hand labelled."
                ),
                blocked_on_person=True,
                instructions=(
                    "Run `ict label` and mark 100 charts per concept, then "
                    "`ict verify --reviewed`. This one cannot be delegated: "
                    "the detectors were written from the same definitions an "
                    "agent would read, so an agent marking them would agree "
                    "with the code by construction and the score would measure "
                    "nothing. See docs/labelling.md."
                ),
            )
        if not state.has_reviewed:
            return Step(
                name="gate 1 scoring",
                reason="Labels exist but reviewed.csv is missing.",
                blocked_on_person=True,
                instructions=(
                    "Press Download labels on the labelling page again: it "
                    "writes reviewed.csv alongside labels.csv. Without it, "
                    "charts you reviewed and correctly left blank are skipped, "
                    "so false positives on quiet days never count."
                ),
            )
        return Step(
            name="gate 1 verify",
            reason=f"{state.labelled_charts} labelled charts are ready to score.",
            command=["verify", str(DATA), "--labels", str(LABELS),
                     "--reviewed", str(REVIEWED)],
        )

    if state.gate2 is not True:
        return Step(
            name="gate 2 in sample",
            reason="The detectors have passed the labelling gate.",
            command=["backtest", str(DATA), "--verified"],
        )

    if state.gate3 is not True:
        return Step(
            name="gate 3 walk forward",
            reason="In sample results are in.",
            command=["rank", str(DATA), "--train-days", "365", "--test-days", "90"],
        )

    if state.gate4 is not True:
        return Step(
            name="gate 4 robustness",
            reason="Walk forward results are in.",
            command=["robustness", str(DATA)],
        )

    return Step(
        name="paper trading",
        reason="Gates 1 to 4 have passed.",
        blocked_on_person=True,
        instructions=(
            "Everything a machine can check has been checked. Paper trading "
            "runs for three months or 100 trades and starts when you start it: "
            "`ict live <parquet> --execute`. Read docs/live.md first, and set "
            "the halt from the worst drawdown the backtest saw."
        ),
    )


def run_step(step: Step, root: Path | None = None, timeout: int = 7200) -> tuple[int, str]:
    """Run one step, refusing anything not on the allow list.

    The allow list is the safety boundary, not a convenience. It is what stops
    a future edit, or a mistake, from turning `advance` into something that can
    place an order.
    """
    if not step.command:
        return 0, "nothing to run"
    if step.command[0] not in ALLOWED:
        raise ValueError(
            f"`advance` refuses to run {step.command[0]!r}: not on the allow "
            f"list {ALLOWED}. Anything that places an order or changes a "
            "parameter is deliberately absent."
        )

    result = subprocess.run(
        ["python", "-m", "ict.cli", *step.command],
        cwd=str(root or "."),
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return result.returncode, (result.stdout or "") + (result.stderr or "")


def record(step: Step, code: int, root: Path | None = None) -> Path | None:
    """Write the pass or fail marker for a gate step.

    Gate commands exit non-zero when their criteria fail, so the marker is the
    command's own verdict rather than a judgement made here.
    """
    number = {"gate 1 verify": 1, "gate 2 in sample": 2,
              "gate 3 walk forward": 3, "gate 4 robustness": 4}.get(step.name)
    if number is None:
        return None

    results = Path(root or ".") / RESULTS
    results.mkdir(parents=True, exist_ok=True)
    passed = results / f"gate{number}.passed"
    failed = results / f"gate{number}.failed"
    for path in (passed, failed):
        path.unlink(missing_ok=True)

    marker = passed if code == 0 else failed
    marker.write_text(f"{pd.Timestamp.now(tz='UTC')}\n")
    return marker


def report(state: State, step: Step) -> str:
    """What is done, what is next, and who has to do it."""
    icons = {True: "PASS", False: "FAIL", None: "  - "}
    lines = ["Project state", "=" * 62]

    lines.append(
        f"  credentials       {'present' if state.has_token else 'missing'}"
        + (f" ({state.environment})" if state.environment else "")
    )
    lines.append(
        f"  market data       {f'{state.candles:,} candles, {state.span}' if state.has_data else 'none'}"
    )
    for name, value in state.gates.items():
        lines.append(f"  gate {name:<14}{icons[value]}")

    lines += ["", f"Next: {step.name}", "-" * 62, step.reason]
    if step.is_mine:
        lines.append("")
        lines.append("Runnable now: ict " + " ".join(step.command))
    else:
        lines += ["", "This one needs you.", "", step.instructions]
    return "\n".join(lines)
