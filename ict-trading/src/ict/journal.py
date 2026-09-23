"""The trade journal: what actually happened, kept where it cannot be edited away.

The record's outsider verdict is the reason this exists: "AI that makes the
right decisions" sounds like every scam trading bot, and "a visible, honest
journal of tested results is what would make anyone trust it".

So the journal appends and never rewrites. Each row is one closed trade with
the reasoning that produced it, and a run that ends badly leaves its rows
behind. A journal you can quietly correct is a marketing document.

It is deliberately a CSV. A file anyone can open in a spreadsheet and check
against the broker's own statement is worth more than a database nobody but
this program can read.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path

import pandas as pd

from .config import MARKET_TZ
from .timeframes.sessions import kill_zone_of

#: Every column, in order. Fixed so a journal written by one version still
#: reads in the next.
COLUMNS = (
    "closed_at",
    "opened_at",
    "instrument",
    "model",
    "direction",
    "entry",
    "exit",
    "stop",
    "target",
    "size",
    "outcome",
    "gross",
    "costs",
    "net",
    "r_multiple",
    "session",
    "reason",
    "review_action",
    "review_reason",
    "source",
)


@dataclass
class Entry:
    """One closed trade, as the journal stores it."""

    closed_at: pd.Timestamp
    opened_at: pd.Timestamp
    instrument: str
    model: str
    direction: str
    entry: float
    exit: float
    stop: float
    target: float
    size: float
    outcome: str
    gross: float
    costs: float
    net: float
    r_multiple: float
    session: str = ""
    reason: str = ""
    review_action: str = ""
    review_reason: str = ""
    #: "backtest", "paper" or "live". Mixing them in one file without saying
    #: which is which is how a paper record becomes a live claim.
    source: str = "backtest"


@dataclass
class Journal:
    """An append only CSV of closed trades."""

    path: Path
    instrument: str = "EUR_USD"
    source: str = "backtest"
    entries: list[Entry] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.path = Path(self.path)

    def add(self, trade, model: str = "", review=None) -> Entry:
        """Record one closed trade."""
        stamp = pd.Timestamp(trade.opened_at)
        entry = Entry(
            closed_at=pd.Timestamp(trade.closed_at),
            opened_at=stamp,
            instrument=self.instrument,
            model=model,
            direction=trade.direction,
            entry=float(trade.entry),
            exit=float(trade.exit),
            stop=float(trade.stop),
            target=float(trade.target),
            size=float(trade.size),
            outcome=trade.outcome,
            gross=float(trade.gross),
            costs=float(trade.costs),
            net=float(trade.net),
            r_multiple=float(trade.r_multiple),
            session=str(kill_zone_of(pd.DatetimeIndex([stamp])).iloc[0] or ""),
            reason=trade.reason,
            review_action=getattr(review, "action", "") if review else "",
            review_reason=getattr(review, "reason", "") if review else "",
            source=self.source,
        )
        self.entries.append(entry)
        return entry

    def append(self, entry: Entry) -> Path:
        """Write one row immediately, creating the file with a header if new.

        Written per trade rather than at the end, because a process that dies
        holding its results has no results. A live run that crashes at 3am must
        still have every trade before the crash on disk.
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)
        new = not self.path.exists()
        frame = pd.DataFrame([asdict(entry)])[list(COLUMNS)]
        frame.to_csv(self.path, mode="a", header=new, index=False)
        return self.path

    def add_and_append(self, trade, model: str = "", review=None) -> Entry:
        entry = self.add(trade, model=model, review=review)
        self.append(entry)
        return entry

    def write_all(self) -> Path:
        """Write every entry held in memory. For a backtest, which has them all."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        frame = self.to_frame()
        frame.to_csv(self.path, index=False)
        return self.path

    def to_frame(self) -> pd.DataFrame:
        if not self.entries:
            return pd.DataFrame(columns=list(COLUMNS))
        return pd.DataFrame([asdict(e) for e in self.entries])[list(COLUMNS)]


def read_journal(path: str | Path) -> pd.DataFrame:
    """Read a journal back, with its timestamps intact."""
    frame = pd.read_csv(path)
    for column in ("closed_at", "opened_at"):
        if column in frame.columns:
            stamps = pd.to_datetime(frame[column], errors="coerce", utc=True)
            frame[column] = stamps
    return frame


def summarise(frame: pd.DataFrame, since: pd.Timestamp | None = None) -> str:
    """The daily summary the record asks for after the New York session.

    Broken down by model and by session, because "down 1.2R today" is a mood
    and "down 1.2R, all of it in the London window, all from one model" is
    something to act on.
    """
    if frame.empty:
        return "No trades journalled."

    if since is not None:
        frame = frame.loc[frame["closed_at"] >= pd.Timestamp(since)]
    if frame.empty:
        return "No trades in that period."

    total_r = float(frame["r_multiple"].sum())
    net = float(frame["net"].sum())
    wins = int((frame["net"] > 0).sum())
    trades = len(frame)

    sources = sorted(set(frame["source"].dropna()))
    lines = [
        "Journal summary",
        "=" * 66,
        f"{trades} trades, {', '.join(sources) if sources else 'unknown source'}",
        f"{frame['closed_at'].min()} to {frame['closed_at'].max()}",
        "",
        f"  net                 {net:+,.2f}",
        f"  total R             {total_r:+.2f}",
        f"  expectancy          {total_r / trades:+.3f} R per trade",
        f"  win rate            {wins / trades:.1%}  ({wins} of {trades})",
        f"  costs paid          {float(frame['costs'].sum()):,.2f}",
    ]

    if "model" in frame.columns and frame["model"].notna().any():
        lines += ["", "By model", "-" * 66]
        for model, group in frame.groupby("model"):
            if not str(model):
                continue
            lines.append(
                f"  {str(model):<24}{len(group):>5} trades  "
                f"{group['r_multiple'].sum():+8.2f}R"
            )

    if "session" in frame.columns:
        # Trades opened outside every kill zone are shown too, under a name,
        # so the rows add up to the total. A breakdown that silently drops
        # two thirds of the trades invites the reader to trust the third that
        # is left.
        # fillna before astype: pandas 3 keeps NA through `astype(str)`, and a
        # NaN key is dropped by groupby, which is what silently hid two thirds
        # of the trades here.
        sessions = frame["session"].fillna("").astype(str).replace(
            {"": "outside a kill zone", "nan": "outside a kill zone",
             "None": "outside a kill zone"}
        )
        lines += ["", "By session", "-" * 66]
        for session, group in frame.groupby(sessions):
            lines.append(
                f"  {str(session):<24}{len(group):>5} trades  "
                f"{group['r_multiple'].sum():+8.2f}R"
            )

    blocked = frame.loc[frame["review_action"].astype(str) == "reduce"]
    if not blocked.empty:
        lines += [
            "",
            f"{len(blocked)} trades were shrunk by the review layer. "
            "Score it with `ict review-audit`.",
        ]

    if "live" not in sources:
        lines += [
            "",
            "No live trades in this journal. Nothing here is a record of money.",
        ]
    return "\n".join(lines)


def daily_breakdown(frame: pd.DataFrame) -> pd.DataFrame:
    """R per New York day, which is the series a drawdown is read from."""
    if frame.empty:
        return pd.DataFrame(columns=["date", "trades", "r_multiple", "net"])
    local = frame["closed_at"].dt.tz_convert(MARKET_TZ).dt.date
    grouped = frame.groupby(local).agg(
        trades=("r_multiple", "size"),
        r_multiple=("r_multiple", "sum"),
        net=("net", "sum"),
    )
    return grouped.reset_index(names="date")
