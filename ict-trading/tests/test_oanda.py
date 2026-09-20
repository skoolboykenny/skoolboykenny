"""Tests for the OANDA client, against a fake transport.

Nothing here touches the network. The point is the parts that are easy to get
wrong and expensive to find out about later: paging, incomplete candles, the
stored layout, and retrying the right failures.
"""

from __future__ import annotations

import json

import pandas as pd
import pytest

from ict.data.loader import read_parquet
from ict.data.oanda import (
    Credentials,
    OandaClient,
    OandaError,
    candles_to_frame,
    combine,
    download,
    months,
)


def candle(minute: int, complete: bool = True, bid: float = 1.1000) -> dict:
    """One OANDA candle, priced so bid and ask are a pip apart."""
    stamp = pd.Timestamp("2024-03-04 00:00", tz="UTC") + pd.Timedelta(minutes=minute)
    ask = bid + 0.0001
    return {
        "time": stamp.strftime("%Y-%m-%dT%H:%M:%S.000000000Z"),
        "complete": complete,
        "volume": 10,
        "bid": {"o": f"{bid:.5f}", "h": f"{bid + 0.0002:.5f}",
                "l": f"{bid - 0.0002:.5f}", "c": f"{bid + 0.0001:.5f}"},
        "ask": {"o": f"{ask:.5f}", "h": f"{ask + 0.0002:.5f}",
                "l": f"{ask - 0.0002:.5f}", "c": f"{ask + 0.0001:.5f}"},
    }


class FakeResponse:
    def __init__(self, payload, status_code=200, lines=None):
        self._payload = payload
        self.status_code = status_code
        self.text = json.dumps(payload) if payload is not None else ""
        self._lines = lines or []

    def json(self):
        return self._payload

    def iter_lines(self):
        for line in self._lines:
            yield line


class FakeSession:
    """Serves queued responses and records what was asked for."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.headers = {}

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs.get("params")))
        if not self.responses:
            return FakeResponse({"candles": []})
        nxt = self.responses.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt


def client(responses) -> OandaClient:
    return OandaClient(
        credentials=Credentials(token="t", account_id="101-001-1-001"),
        session=FakeSession(responses),
        max_attempts=3,
    )


# --- credentials ------------------------------------------------------------


def test_a_missing_token_says_what_to_do(monkeypatch):
    monkeypatch.delenv("OANDA_API_TOKEN", raising=False)
    with pytest.raises(OandaError, match="OANDA_API_TOKEN"):
        Credentials.from_env()


def test_an_unknown_environment_is_refused(monkeypatch):
    monkeypatch.setenv("OANDA_API_TOKEN", "t")
    monkeypatch.setenv("OANDA_ENVIRONMENT", "production")
    with pytest.raises(OandaError, match="practice"):
        Credentials.from_env()


def test_practice_and_live_differ_only_by_host(monkeypatch):
    monkeypatch.setenv("OANDA_API_TOKEN", "t")
    monkeypatch.setenv("OANDA_ENVIRONMENT", "live")
    assert Credentials.from_env().is_live
    monkeypatch.setenv("OANDA_ENVIRONMENT", "practice")
    assert not Credentials.from_env().is_live

    practice = client([])
    assert "fxpractice" in practice.rest_host
    assert "fxpractice" in practice.stream_host


def test_the_token_is_sent_as_a_bearer_header():
    api = client([])
    assert api.session.headers["Authorization"] == "Bearer t"


# --- candles ----------------------------------------------------------------


def test_incomplete_candles_are_dropped():
    """A forming candle's high and low are not final, so it is lookahead."""
    frame = candles_to_frame([candle(0), candle(1, complete=False)])
    assert len(frame) == 1
    assert frame.index[0] == pd.Timestamp("2024-03-04 00:00", tz="UTC")


def test_the_frame_carries_both_sides_the_mid_and_the_spread():
    frame = candles_to_frame([candle(0)])
    row = frame.iloc[0]
    assert row["bid_close"] == pytest.approx(1.1001)
    assert row["ask_close"] == pytest.approx(1.1002)
    assert row["mid_close"] == pytest.approx(1.10015)
    assert row["spread"] == pytest.approx(0.0001)


def test_an_empty_page_still_has_the_right_columns():
    frame = candles_to_frame([])
    assert frame.empty
    assert "bid_close" in frame.columns


def test_the_frame_reads_back_through_the_normal_loader(tmp_path):
    """The stored layout must be the one the rest of the project expects."""
    frame = candles_to_frame([candle(i) for i in range(5)])
    path = tmp_path / "eurusd.parquet"
    frame.to_parquet(path, engine="pyarrow", index=True)

    mid = read_parquet(path)
    assert list(mid.columns)[:5] == ["open", "high", "low", "close", "volume"]
    assert mid["close"].iloc[0] == pytest.approx(1.10015)

    bid = read_parquet(path, side="bid")
    assert bid["close"].iloc[0] == pytest.approx(1.1001)
    assert "spread" in bid.columns


def test_paging_follows_the_last_candle_of_each_page():
    api = client([
        FakeResponse({"candles": [candle(i) for i in range(3)]}),
        FakeResponse({"candles": [candle(i) for i in range(3, 6)]}),
        FakeResponse({"candles": []}),
    ])
    pages = list(
        api.candles(
            "EUR_USD",
            pd.Timestamp("2024-03-04", tz="UTC"),
            pd.Timestamp("2024-03-05", tz="UTC"),
        )
    )
    assert [len(p) for p in pages] == [3, 3]

    # The second request must start where the first page ended, or candles are
    # silently skipped.
    second = api.session.calls[1][2]
    assert second["from"].startswith("2024-03-04T00:02")
    assert second["includeFirst"] == "false"


def test_paging_stops_when_a_page_does_not_advance():
    """A server repeating itself must not spin the loop for ever."""
    api = client([FakeResponse({"candles": [candle(0)]})] * 10)
    pages = list(
        api.candles(
            "EUR_USD",
            pd.Timestamp("2024-03-04", tz="UTC"),
            pd.Timestamp("2024-03-05", tz="UTC"),
        )
    )
    assert len(pages) == 1


def test_bid_and_ask_are_always_requested():
    api = client([FakeResponse({"candles": []})])
    list(api.candles("EUR_USD", pd.Timestamp("2024-03-04", tz="UTC"),
                     pd.Timestamp("2024-03-05", tz="UTC")))
    assert api.session.calls[0][2]["price"] == "BA"


# --- retries ----------------------------------------------------------------


def test_rate_limiting_is_retried(monkeypatch):
    monkeypatch.setattr("ict.data.oanda._time.sleep", lambda _: None)
    api = client([
        FakeResponse({"errorMessage": "slow down"}, status_code=429),
        FakeResponse({"candles": [candle(0)]}),
    ])
    assert len(api.candle_page("EUR_USD", pd.Timestamp("2024-03-04", tz="UTC"),
                               pd.Timestamp("2024-03-05", tz="UTC"))) == 1


def test_a_bad_token_is_not_retried():
    """401 is a configuration error. Retrying it only delays the message."""
    api = client([FakeResponse({"errorMessage": "Insufficient authorization"},
                               status_code=401)])
    with pytest.raises(OandaError, match="401"):
        api.get("/v3/accounts")
    assert len(api.session.calls) == 1


def test_a_network_failure_is_retried_then_reported(monkeypatch):
    monkeypatch.setattr("ict.data.oanda._time.sleep", lambda _: None)
    api = client([OSError("connection reset")] * 3)
    with pytest.raises(OandaError, match="connection reset"):
        api.get("/v3/accounts")
    assert len(api.session.calls) == 3


# --- downloading ------------------------------------------------------------


def test_months_splits_on_calendar_boundaries():
    spans = months(
        pd.Timestamp("2024-01-15", tz="UTC"), pd.Timestamp("2024-04-02", tz="UTC")
    )
    assert [f"{s:%Y-%m}" for s, _ in spans] == ["2024-01", "2024-02", "2024-03", "2024-04"]
    assert spans[-1][1] == pd.Timestamp("2024-04-02", tz="UTC")


def test_download_skips_months_already_on_disk(tmp_path, monkeypatch):
    monkeypatch.setattr("ict.data.oanda._time.sleep", lambda _: None)
    api = client([FakeResponse({"candles": [candle(i) for i in range(3)]})] * 20)
    start, end = pd.Timestamp("2024-01-01", tz="UTC"), pd.Timestamp("2024-03-01", tz="UTC")

    download("EUR_USD", start, end, tmp_path, client=api)
    first_calls = len(api.session.calls)

    # The second pass re-downloads only the final month, which may have been
    # written before that month finished.
    download("EUR_USD", start, end, tmp_path, client=api)
    assert len(api.session.calls) < first_calls * 2


def test_combine_merges_chunks_and_drops_repeats(tmp_path):
    one = candles_to_frame([candle(i) for i in range(3)])
    two = candles_to_frame([candle(i) for i in range(2, 5)])
    (a, b) = tmp_path / "a.parquet", tmp_path / "b.parquet"
    one.to_parquet(a, engine="pyarrow", index=True)
    two.to_parquet(b, engine="pyarrow", index=True)

    merged = combine([a, b])
    assert len(merged) == 5
    assert merged.index.is_monotonic_increasing
    assert not merged.index.duplicated().any()
