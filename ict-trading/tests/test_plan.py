"""Tests for the daily plan, the journal and the alerts.

The plan is read only, so what is tested is that it says the right thing and
never sees further than the engine could. The journal is tested for the one
property that makes it worth trusting: it appends and does not rewrite. The
alerts are tested for the one that matters at 3am: a broken sink never takes
down a loop holding a position.
"""

from __future__ import annotations

import pandas as pd
import pytest

from ict.alerts import Alert, Alerts, ConsoleSink, FileSink, WebhookSink
from ict.cli import synthetic_candles
from ict.journal import Entry, Journal, daily_breakdown, read_journal, summarise
from ict.news import NewsGate
from ict.plan import build_plan


@pytest.fixture(scope="module")
def candles():
    return synthetic_candles(days=30)


def calendar_frame(rows) -> pd.DataFrame:
    return pd.DataFrame([
        {"time": pd.Timestamp(t).tz_localize("UTC")
                 if pd.Timestamp(t).tz is None else pd.Timestamp(t),
         "currency": c, "impact": i,
         "event": e, "actual": None, "forecast": None, "previous": None,
         "revised": None}
        for t, c, i, e in rows
    ])


# --- the plan ---------------------------------------------------------------


def test_a_plan_reads_a_bias_and_a_draw(candles):
    plan = build_plan(candles, instrument="EUR_USD")
    assert plan.bias in ("long", "short", "no trade")
    if not plan.is_no_trade:
        assert plan.draw is not None
        assert plan.reason


def test_a_plan_never_sees_past_its_own_moment(candles):
    """A plan rebuilt for a past day must say what it would have said then."""
    cut = candles.index[len(candles) // 2]
    as_of = build_plan(candles, now=cut)
    truncated = build_plan(candles.loc[candles.index <= cut])

    assert as_of.price == pytest.approx(truncated.price)
    assert as_of.bias == truncated.bias
    assert as_of.draw == truncated.draw
    assert as_of.levels == truncated.levels


def test_a_plan_refuses_an_empty_series():
    with pytest.raises(ValueError, match="empty"):
        build_plan(pd.DataFrame())


def test_too_little_history_is_a_no_trade_not_a_guess():
    plan = build_plan(synthetic_candles(days=30).head(60))
    assert plan.is_no_trade
    assert "history" in plan.reason


def test_the_message_is_one_line_in_the_records_shape(candles):
    plan = build_plan(candles)
    message = plan.message()
    assert "\n" not in message
    if not plan.is_no_trade:
        assert "bias" in message and "draw at" in message


def test_a_no_trade_day_says_so_rather_than_picking_a_side(candles):
    plan = build_plan(candles)
    plan.bias = "no trade"
    plan.reason = "bias unclear"
    assert plan.is_no_trade
    assert "no trade" in plan.message()


def test_the_days_releases_appear_in_the_plan(candles):
    at = candles.index[len(candles) // 2]
    gate = NewsGate(calendar_frame([
        (at + pd.Timedelta(hours=6), "USD", "high", "CPI m/m"),
        (at + pd.Timedelta(days=9), "USD", "high", "Far Away"),
    ]))
    plan = build_plan(candles, now=at, news_gate=gate)
    assert len(plan.blackouts) == 1
    assert "CPI" in plan.blackouts[0]


def test_an_empty_calendar_and_a_quiet_day_do_not_read_the_same():
    """Both have no blackouts and they mean opposite things."""
    data = synthetic_candles(days=30)
    none_loaded = build_plan(data)
    loaded_but_quiet = build_plan(
        data, news_gate=NewsGate(calendar_frame([
            ("2020-01-01 12:00", "USD", "high", "Ancient History")
        ]))
    )
    assert "No calendar loaded" in none_loaded.report()
    assert "No high impact release" in loaded_but_quiet.report()


def test_an_open_position_turns_the_plan_to_no_trade(candles):
    """The loop will not enter while one is live, so the plan should not imply it will."""

    class Busy:
        def account(self):
            return {"balance": "10000", "NAV": "9900", "openPositionCount": 1}

    plan = build_plan(candles, broker=Busy())
    assert plan.is_no_trade
    assert any("already open" in w for w in plan.warnings)


def test_an_unreachable_broker_is_a_warning_not_a_crash(candles):
    class Broken:
        def account(self):
            raise RuntimeError("connection refused")

    plan = build_plan(candles, broker=Broken())
    assert plan.account == {}
    assert any("unreachable" in w for w in plan.warnings)


def test_equity_comes_from_nav_not_balance(candles):
    class Account:
        def account(self):
            return {"balance": "10000", "NAV": "9500", "openPositionCount": 0}

    plan = build_plan(candles, broker=Account())
    assert plan.account["equity (NAV)"] == pytest.approx(9500)


# --- the journal ------------------------------------------------------------


def entry(net: float = 100.0, r: float = 2.0, **overrides) -> Entry:
    fields = {
        "closed_at": pd.Timestamp("2024-03-08 15:00", tz="UTC"),
        "opened_at": pd.Timestamp("2024-03-08 14:00", tz="UTC"),
        "instrument": "EUR_USD",
        "model": "silver_bullet",
        "direction": "long",
        "entry": 1.0850,
        "exit": 1.0870,
        "stop": 1.0840,
        "target": 1.0880,
        "size": 1000.0,
        "outcome": "target",
        "gross": net,
        "costs": 0.0,
        "net": net,
        "r_multiple": r,
        "session": "ny_am",
        "reason": "test",
        "source": "paper",
    }
    fields.update(overrides)
    return Entry(**fields)


def test_the_journal_appends_and_does_not_rewrite(tmp_path):
    """A journal you can quietly correct is a marketing document."""
    journal = Journal(path=tmp_path / "journal.csv")
    journal.append(entry(net=100.0))
    journal.append(entry(net=-50.0))

    frame = read_journal(tmp_path / "journal.csv")
    assert len(frame) == 2
    assert list(frame["net"]) == [100.0, -50.0]

    # A second journal pointed at the same file adds to it rather than
    # replacing it, which is what survives a crash and a restart.
    Journal(path=tmp_path / "journal.csv").append(entry(net=25.0))
    assert len(read_journal(tmp_path / "journal.csv")) == 3


def test_the_header_is_written_once(tmp_path):
    journal = Journal(path=tmp_path / "journal.csv")
    for _ in range(3):
        journal.append(entry())
    text = (tmp_path / "journal.csv").read_text()
    assert text.count("closed_at") == 1


def test_columns_are_fixed_so_an_old_journal_still_reads(tmp_path):
    from ict.journal import COLUMNS

    journal = Journal(path=tmp_path / "journal.csv")
    journal.append(entry())
    assert list(read_journal(tmp_path / "journal.csv").columns) == list(COLUMNS)


def test_a_backtest_trade_becomes_a_journal_entry():
    from ict.backtest.broker import Trade

    trade = Trade(
        opened_at=pd.Timestamp("2024-03-08 14:00", tz="UTC"),
        closed_at=pd.Timestamp("2024-03-08 15:00", tz="UTC"),
        direction="long", entry=1.0, exit=1.002, stop=0.999, target=1.003,
        size=1000.0, reason="sweep then gap", outcome="target",
        gross=2.0, costs=0.2,
    )
    journal = Journal(path="unused.csv", source="backtest")
    written = journal.add(trade, model="silver_bullet")
    assert written.net == pytest.approx(1.8)
    assert written.model == "silver_bullet"
    assert written.source == "backtest"


def test_the_summary_breaks_down_by_model_and_session(tmp_path):
    journal = Journal(path=tmp_path / "j.csv")
    journal.append(entry(net=100.0, r=2.0, model="silver_bullet"))
    journal.append(entry(net=-50.0, r=-1.0, model="turtle_soup"))

    text = summarise(read_journal(tmp_path / "j.csv"))
    assert "silver_bullet" in text
    assert "turtle_soup" in text
    assert "ny_am" in text
    assert "+0.500 R per trade" in text


def test_a_journal_with_no_live_trades_says_so(tmp_path):
    journal = Journal(path=tmp_path / "j.csv")
    journal.append(entry(source="paper"))
    assert "Nothing here is a record of money" in summarise(read_journal(tmp_path / "j.csv"))


def test_an_empty_journal_summarises_to_nothing_rather_than_crashing():
    assert "No trades" in summarise(pd.DataFrame())


def test_the_daily_breakdown_groups_by_new_york_day(tmp_path):
    journal = Journal(path=tmp_path / "j.csv")
    # 01:00 UTC is the previous New York day, which is the day a trader had.
    journal.append(entry(closed_at=pd.Timestamp("2024-03-08 01:00", tz="UTC"), r=1.0))
    journal.append(entry(closed_at=pd.Timestamp("2024-03-08 15:00", tz="UTC"), r=2.0))

    daily = daily_breakdown(read_journal(tmp_path / "j.csv"))
    assert len(daily) == 2


# --- alerts -----------------------------------------------------------------


def test_a_broken_sink_never_takes_down_the_loop():
    """A webhook timing out at 3am cannot stop a process holding a position."""

    class Broken:
        name = "broken"

        def send(self, alert):
            raise RuntimeError("connection timed out")

    alerts = Alerts(sinks=[Broken()])
    alerts.fill("filled at 1.08501")
    alerts.halt("drawdown")

    assert "broken" in alerts.failed
    assert len(alerts.sent) == 2


def test_a_failed_sink_is_tried_once_and_then_left_alone():
    """Retrying a broken webhook every fill turns an outage into a busy loop."""
    attempts = []

    class Broken:
        name = "broken"

        def send(self, alert):
            attempts.append(alert)
            raise RuntimeError("down")

    alerts = Alerts(sinks=[Broken()])
    for _ in range(5):
        alerts.info("tick")
    assert len(attempts) == 1


def test_halts_and_errors_are_urgent_and_nothing_else_is():
    alerts = Alerts(sinks=[])
    alerts.info("plan ready")
    alerts.fill("filled")
    alerts.halt("stale stream")
    alerts.error("broker unreachable")
    assert [a.level for a in alerts.urgent] == ["halt", "error"]


def test_a_file_sink_survives_the_terminal_closing(tmp_path):
    path = tmp_path / "alerts.log"
    alerts = Alerts(sinks=[FileSink(path)])
    alerts.fill("one")
    alerts.halt("two")
    assert len(path.read_text().strip().splitlines()) == 2


def test_a_webhook_without_a_url_does_nothing():
    posted = []

    class Session:
        def post(self, *args, **kwargs):
            posted.append(kwargs)

    WebhookSink(url="", session=Session()).send(Alert("halt", "x"))
    assert posted == []


def test_a_webhook_filters_the_chatter_but_never_a_halt():
    posted = []

    class Session:
        def post(self, url, **kwargs):
            posted.append(kwargs)

    sink = WebhookSink(url="https://example.invalid/hook", session=Session(),
                       minimum_level="fill")
    sink.send(Alert("info", "quiet"))
    assert posted == []
    sink.send(Alert("halt", "loud"))
    assert len(posted) == 1


def test_a_webhook_url_comes_from_the_environment(monkeypatch):
    """A bot token in a commit is a bot anyone can drive."""
    monkeypatch.delenv("ICT_ALERT_WEBHOOK", raising=False)
    assert WebhookSink.from_env() is None
    monkeypatch.setenv("ICT_ALERT_WEBHOOK", "https://example.invalid/hook")
    assert WebhookSink.from_env().url == "https://example.invalid/hook"


def test_the_session_breakdown_adds_up_to_the_total(tmp_path):
    """A breakdown that drops trades invites trust in the ones it kept.

    Trades opened outside every kill zone had a NaN session, and pandas 3
    keeps NA through `astype(str)` while groupby drops NaN keys, so two
    thirds of a run vanished from the table without a word.
    """
    journal = Journal(path=tmp_path / "j.csv")
    journal.append(entry(r=1.0, session="ny_am"))
    journal.append(entry(r=-1.0, session=""))
    journal.append(entry(r=-2.0, session=""))

    text = summarise(read_journal(tmp_path / "j.csv"))
    assert "outside a kill zone" in text
    counted = sum(
        int(line.split()[-3]) for line in text.splitlines()
        if line.strip().endswith("R") and "trades" in line
    )
    assert counted == 3 * 2  # each row is counted once per breakdown, model and session
