"""Tests for the live path, against a fake broker.

Nothing here touches a network or an account. What is tested is the behaviour
that only matters live: that a forming candle never reaches a detector, that
every order carries its own stop, and that the halt conditions halt.
"""

from __future__ import annotations

import pandas as pd
import pytest

from ict.backtest.strategy import Setup
from ict.data.oanda import Credentials, OandaClient, OandaError
from ict.live.broker import Instrument, LiveBroker
from ict.live.runner import CandleBuilder, Guards, LiveRunner
from ict.cli import synthetic_candles


INSTRUMENT = {
    "instruments": [
        {"name": "EUR_USD", "displayPrecision": 5, "minimumTradeSize": "1",
         "maximumOrderUnits": "100000000", "marginRate": "0.02"}
    ]
}


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload
        self.status_code = 200
        self.text = ""

    def json(self):
        return self.payload


class FakeSession:
    """Answers by path, and records every request."""

    def __init__(self, routes=None):
        self.routes = routes or {}
        self.calls = []
        self.headers = {}

    def request(self, method, url, **kwargs):
        self.calls.append({"method": method, "url": url, **kwargs})
        for fragment, payload in self.routes.items():
            if fragment in url:
                value = payload(self) if callable(payload) else payload
                return FakeResponse(value)
        return FakeResponse({})


def broker(routes=None) -> LiveBroker:
    routes = {"/instruments": INSTRUMENT, **(routes or {})}
    client = OandaClient(
        credentials=Credentials(token="t", account_id="101-001-1-001"),
        session=FakeSession(routes),
    )
    return LiveBroker(client, "EUR_USD")


def setup(direction="long") -> Setup:
    if direction == "long":
        return Setup("long", limit=1.08501234, stop=1.08401234, target=1.08801234,
                     reason="test", expires_at=pd.Timestamp("2024-03-04 12:00", tz="UTC"))
    return Setup("short", limit=1.0850, stop=1.0860, target=1.0820, reason="test")


# --- rounding ---------------------------------------------------------------


def test_prices_are_rounded_to_the_instruments_precision():
    """OANDA rejects a price with more precision than the instrument allows."""
    instrument = Instrument("EUR_USD", display_precision=5)
    assert instrument.round_price(1.08501234) == "1.08501"
    assert instrument.round_price(1.085015) == "1.08502"

    jpy = Instrument("USD_JPY", display_precision=3)
    assert jpy.round_price(151.23456) == "151.235"


def test_units_are_whole_and_capped():
    instrument = Instrument("EUR_USD", maximum_trade_size=5000)
    assert instrument.round_units(1234.9) == 1234
    assert instrument.round_units(999_999) == 5000


# --- orders -----------------------------------------------------------------


def test_every_order_carries_its_own_stop_and_target():
    """A position must never be naked, not even between a fill and a follow up."""
    live = broker({"/orders": {"orderCreateTransaction": {"id": "17", "time": "2024-03-04T11:00:00.000000000Z"}}})
    live.place(setup(), size=1000)

    body = live.client.session.calls[-1]["json"]["order"]
    assert body["price"] == "1.08501"
    assert body["stopLossOnFill"]["price"] == "1.08401"
    assert body["takeProfitOnFill"]["price"] == "1.08801"
    assert body["type"] == "LIMIT"


def test_a_short_is_sent_as_negative_units():
    live = broker({"/orders": {"orderCreateTransaction": {"id": "18", "time": "2024-03-04T11:00:00.000000000Z"}}})
    live.place(setup("short"), size=2000)
    assert live.client.session.calls[-1]["json"]["order"]["units"] == "-2000"


def test_an_order_expires_with_its_window():
    """A Silver Bullet entry filled at lunchtime is a different strategy."""
    live = broker({"/orders": {"orderCreateTransaction": {"id": "19", "time": "2024-03-04T11:00:00.000000000Z"}}})
    live.place(setup(), size=1000)
    body = live.client.session.calls[-1]["json"]["order"]
    assert body["timeInForce"] == "GTD"
    assert body["gtdTime"].startswith("2024-03-04T12:00:00")


def test_a_size_below_the_minimum_is_refused_not_rounded_up():
    live = broker()
    live._instrument = Instrument("EUR_USD", minimum_trade_size=100)
    with pytest.raises(OandaError, match="minimum trade size"):
        live.place(setup(), size=5)


def test_a_failed_order_is_reported_rather_than_assumed():
    live = broker({"/orders": {"orderRejectTransaction": {"reason": "MARKET_HALTED"}}})
    with pytest.raises(OandaError, match="not created"):
        live.place(setup(), size=1000)


def test_equity_uses_nav_not_balance():
    """Balance ignores an open position's unrealised loss."""
    live = broker({"/summary": {"account": {"balance": "10000", "NAV": "9500"}}})
    assert live.equity() == pytest.approx(9500)


def test_the_kill_switch_cancels_and_closes_everything():
    live = broker({
        "/pendingOrders": {"orders": [{"id": "1"}, {"id": "2"}]},
        "/openTrades": {"trades": [{"id": "9"}]},
    })
    assert live.cancel_all() == 2
    assert live.close_all() == 1


def test_writes_that_create_an_order_are_not_retried():
    """A POST that timed out may still have reached the exchange."""
    calls = []

    class Failing(FakeSession):
        def request(self, method, url, **kwargs):
            calls.append(method)
            raise OSError("timeout")

    client = OandaClient(
        credentials=Credentials(token="t", account_id="1"),
        session=Failing(),
        max_attempts=5,
    )
    with pytest.raises(OandaError):
        client.post("/v3/accounts/1/orders", {"order": {}})
    assert calls == ["POST"]


# --- candle building --------------------------------------------------------


def test_a_forming_candle_is_never_handed_out():
    """The whole project's lookahead rule, at the place it is easiest to break."""
    builder = CandleBuilder()
    base = pd.Timestamp("2024-03-04 12:00:00", tz="UTC")
    for second in (0, 15, 30, 45):
        assert builder.add(base + pd.Timedelta(seconds=second), 1.0850, 1.0851) is None

    closed = builder.add(base + pd.Timedelta(minutes=1), 1.0860, 1.0861)
    assert closed is not None
    assert closed.name == base


def test_a_candle_is_built_from_every_tick_in_its_minute():
    builder = CandleBuilder()
    base = pd.Timestamp("2024-03-04 12:00:00", tz="UTC")
    for second, bid in ((0, 1.0850), (20, 1.0870), (40, 1.0840), (55, 1.0860)):
        builder.add(base + pd.Timedelta(seconds=second), bid, bid + 0.0001)
    candle = builder.add(base + pd.Timedelta(minutes=1), 1.0855, 1.0856)

    assert candle["open"] == pytest.approx(1.08505)
    assert candle["high"] == pytest.approx(1.08705)
    assert candle["low"] == pytest.approx(1.08405)
    assert candle["close"] == pytest.approx(1.08605)
    assert candle["volume"] == 4
    assert candle["spread"] == pytest.approx(0.0001)


def test_a_minute_with_no_ticks_produces_no_candle():
    builder = CandleBuilder()
    assert builder._close() is None


# --- the runner -------------------------------------------------------------


def runner(**kwargs) -> LiveRunner:
    history = synthetic_candles(days=3)
    history["spread"] = 0.00012
    return LiveRunner(broker(), history, dry_run=True, **kwargs)


def test_the_runner_refuses_to_start_without_history():
    """Detectors cannot see structure in a series that began this minute."""
    with pytest.raises(ValueError, match="history"):
        LiveRunner(broker(), pd.DataFrame(), dry_run=True)


def test_heartbeats_keep_the_clock_alive_but_do_not_trade():
    live = runner()
    assert live.on_message({"type": "HEARTBEAT", "time": "2024-03-04T12:00:00Z"}) is None
    assert live.last_message is not None
    assert not live.halted


def test_a_stale_stream_halts_the_loop():
    live = runner(guards=Guards(stale_after=pd.Timedelta(seconds=1)))
    live.last_message = pd.Timestamp.now(tz="UTC") - pd.Timedelta(minutes=5)
    halt = live.check_guards(pd.Timestamp.now(tz="UTC"))
    assert halt is not None
    assert "stale" in halt.reason


def test_the_stale_guard_fires_through_the_real_message_path():
    """The guard was dead: `last_message` was set to now *before* the check,
    so the gap was always zero and only a hand set field could trip it."""
    live = runner(guards=Guards(stale_after=pd.Timedelta(seconds=1)))

    beat = {"type": "HEARTBEAT", "time": "2024-03-04T12:00:00Z"}
    live.on_message(beat)
    assert not live.halted

    # Wind the clock back on the loop's own record of the last message, which
    # is what a dead connection looks like, then let a real message arrive.
    live.last_message = pd.Timestamp.now(tz="UTC") - pd.Timedelta(minutes=5)
    live.on_message(beat)
    assert live.halted is not None
    assert "stale" in live.halted.reason


def test_reconciling_counts_realised_money_not_unrealised(monkeypatch):
    """NAV moves every tick an open position moves.

    Booking those moves as closed results made one position drifting against
    the account look like a run of losses, and the halt that follows flattens
    an account that was never in trouble.
    """
    live = runner()
    live.dry_run = False
    live.risk.equity = 10_000.0

    # The position is 400 down on paper, but nothing has closed.
    live.broker.account = lambda: {"balance": "10000", "NAV": "9600"}
    live.broker.closed_trades_since = lambda since: []

    live.reconcile()
    assert live.consecutive_losses == 0
    assert live.risk.equity == pytest.approx(10_000.0)

    # Now a trade actually closes for a loss, and that does count.
    live.broker.account = lambda: {"balance": "9800", "NAV": "9800"}
    live.reconcile()
    assert live.consecutive_losses == 1
    assert live.risk.equity == pytest.approx(9_800.0)


def test_balance_prefers_realised_over_nav():
    live = broker({"/summary": {"account": {"balance": "10000", "NAV": "9500"}}})
    assert live.balance() == pytest.approx(10_000)
    assert live.equity() == pytest.approx(9_500)


def test_a_drawdown_past_the_guard_halts_the_loop():
    live = runner(guards=Guards(max_drawdown=0.10))
    live.risk.peak_equity = 10_000.0
    live.risk.equity = 8_500.0
    halt = live.check_guards(pd.Timestamp.now(tz="UTC"))
    assert halt is not None and halt.reason == "drawdown"


def test_a_losing_run_halts_the_loop():
    live = runner(guards=Guards(max_consecutive_losses=3))
    live.consecutive_losses = 3
    assert live.check_guards(pd.Timestamp.now(tz="UTC")).reason == "losing run"


def test_a_halt_is_final():
    """A loop that trades through its own kill switch does not have one."""
    live = runner(guards=Guards(max_consecutive_losses=1))
    live.consecutive_losses = 5
    first = live.check_guards(pd.Timestamp.now(tz="UTC"))
    live.consecutive_losses = 0
    assert live.check_guards(pd.Timestamp.now(tz="UTC")) is first


def test_an_untradeable_price_is_ignored():
    live = runner()
    assert live.on_message(
        {"type": "PRICE", "time": "2024-03-04T12:00:00Z", "tradeable": False,
         "bids": [{"price": "1.0850"}], "asks": [{"price": "1.0851"}]}
    ) is None


def test_a_dry_run_never_sends_an_order():
    live = runner()
    base = pd.Timestamp("2024-03-07 12:00:00", tz="UTC")
    for minute in range(3):
        live.on_message({
            "type": "PRICE",
            "time": (base + pd.Timedelta(minutes=minute)).isoformat(),
            "bids": [{"price": "1.0850"}], "asks": [{"price": "1.0851"}],
        })
    assert not any(c["method"] == "POST" for c in live.broker.client.session.calls)
    assert live.placed == []


# --- failures that must not be diagnosed as something worse -----------------


def test_a_refused_order_does_not_flatten_the_account():
    """A rejection is a rejection, not a dead stream.

    Letting an OandaError reach run()'s blanket handler diagnosed "stream
    failed" and halted permanently, which flattens, on the strength of one
    order being too small or one price being stale.
    """
    live = runner()
    live.dry_run = False

    def refuse(*args, **kwargs):
        raise OandaError("ORDER_UNITS_LIMIT_EXCEEDED")

    live.broker.place = refuse
    live.broker.balance = lambda: 10_000.0
    live.broker.equity = lambda: 10_000.0
    live.broker.closed_trades_since = lambda since: []
    live.broker.open_trades = lambda: []
    live.broker.pending_orders = lambda: []

    # Force a setup through, so the only thing under test is the refusal.
    wanted = Setup("long", limit=1.0850, stop=1.0840, target=1.0880, reason="x")
    model = live.model()
    model.find_setup = lambda now, candle: wanted
    model.tradeable_at = lambda now: True
    live.model = lambda: model

    stamp = live.candles.index[-1] + pd.Timedelta(minutes=1)
    candle = live.candles.iloc[-1].copy()
    candle.name = stamp

    assert live.on_candle(candle) is None
    assert live.halted is None, "a refused order must not halt the loop"
    assert live.placed == []


def test_a_restart_does_not_re_journal_what_is_already_written(tmp_path):
    """A halt requires a restart, and the broker still reports the last two
    days of closed trades to the new process."""
    from ict.journal import Entry, Journal

    path = tmp_path / "journal.csv"
    book = Journal(path=path, instrument="EUR_USD", source="paper")
    book.append(
        Entry(
            closed_at=pd.Timestamp("2024-03-08 15:00", tz="UTC"),
            opened_at=pd.Timestamp("2024-03-08 14:00", tz="UTC"),
            instrument="EUR_USD", model="silver_bullet", direction="long",
            entry=1.085, exit=1.087, stop=1.084, target=1.088, size=1000.0,
            outcome="target", gross=100.0, costs=0.0, net=100.0, r_multiple=2.0,
            source="paper", broker_trade_id="17",
        )
    )

    live = LiveRunner(broker(), synthetic_candles(days=3).assign(spread=0.00012),
                      trade_journal=Journal(path=path), dry_run=True)
    assert "17" in live._seen_trades


def test_an_empty_journal_seeds_nothing(tmp_path):
    from ict.journal import Journal

    live = LiveRunner(broker(), synthetic_candles(days=3).assign(spread=0.00012),
                      trade_journal=Journal(path=tmp_path / "none.csv"),
                      dry_run=True)
    assert live._seen_trades == set()


def test_the_journal_entry_balances(tmp_path):
    """gross - costs must equal net, and financing must reach the bottom line."""
    live = LiveRunner(broker(), synthetic_candles(days=3).assign(spread=0.00012),
                      dry_run=True)
    entry = live._journal_entry({
        "id": "9", "instrument": "EUR_USD", "initialUnits": "1000",
        "price": "1.0850", "averageClosePrice": "1.0870",
        "realizedPL": "20.0", "financing": "-0.5",
        "openTime": "2024-03-08T14:00:00.000000000Z",
        "closeTime": "2024-03-08T15:00:00.000000000Z",
        "stopLossOrder": {"price": "1.0840"},
    })
    assert entry.gross - entry.costs == pytest.approx(entry.net)
    assert entry.net == pytest.approx(19.5)
    assert entry.broker_trade_id == "9"


# --- one runner must not reach into another instrument ----------------------


def test_open_trades_and_orders_are_scoped_to_this_instrument():
    """Account wide was wrong both ways: another instrument's position blocked
    this one's entries, and this one's kill switch liquidated the other's."""
    live = broker({
        "/openTrades": {"trades": [
            {"id": "1", "instrument": "EUR_USD"},
            {"id": "2", "instrument": "GBP_USD"},
        ]},
        "/pendingOrders": {"orders": [
            {"id": "7", "instrument": "EUR_USD"},
            {"id": "8", "instrument": "USD_JPY"},
        ]},
    })
    assert [t["id"] for t in live.open_trades()] == ["1"]
    assert [o["id"] for o in live.pending_orders()] == ["7"]
    assert len(live.open_trades(mine_only=False)) == 2
    assert len(live.pending_orders(mine_only=False)) == 2


def test_a_resting_exit_order_is_not_dropped():
    """A take profit or stop loss names its trade, not an instrument, and
    dropping it would hide a resting exit."""
    live = broker({"/pendingOrders": {"orders": [
        {"id": "9", "type": "TAKE_PROFIT", "tradeID": "1"},
    ]}})
    assert len(live.pending_orders()) == 1


def test_the_kill_switch_stays_on_its_own_instrument_by_default():
    live = broker({
        "/openTrades": {"trades": [
            {"id": "1", "instrument": "EUR_USD"},
            {"id": "2", "instrument": "GBP_USD"},
        ]},
        "/pendingOrders": {"orders": [{"id": "7", "instrument": "GBP_USD"}]},
    })
    assert live.close_all() == 1
    assert live.cancel_all() == 0
    assert live.close_all(every_instrument=True) == 2


def test_a_history_with_no_spread_column_still_records_live_spreads():
    """Assigning a row carrying a spread into a frame without the column
    dropped it silently, leaving the spread guard a permanent no-op."""
    history = synthetic_candles(days=3).drop(columns=["spread"], errors="ignore")
    assert "spread" not in history.columns

    live = LiveRunner(broker(), history, dry_run=True)
    candle = pd.Series(
        {"open": 1.085, "high": 1.0855, "low": 1.0845, "close": 1.085,
         "volume": 10.0, "spread": 0.00012},
        name=history.index[-1] + pd.Timedelta(minutes=1),
    )
    live.on_candle(candle)

    assert "spread" in live.candles.columns
    assert live.candles["spread"].dropna().iloc[-1] == pytest.approx(0.00012)
