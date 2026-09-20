"""OANDA v20 client: historical candles and the live price stream.

One integration covers three of the project's needs. The candles endpoint
gives years of 1 minute bid and ask history, which is the data the whole
project has been waiting on. The pricing stream feeds the same detectors in
real time. The orders endpoint, used by the live runner, takes exactly the
limit, stop and target a :class:`~ict.backtest.strategy.Setup` already
produces.

**Credentials never live in this repository.** They come from the environment:

    export OANDA_API_TOKEN=...        # from the account's "Manage API Access"
    export OANDA_ACCOUNT_ID=101-004-...
    export OANDA_ENVIRONMENT=practice # or "live"

A practice account is free and needs no deposit, and the two environments
differ only by hostname and token, so everything up to and including paper
trading runs here with no money at risk.

**Bid and ask are downloaded together, not the mid.** The spread is what
decides whether a minute was tradeable at all, and a backtest that fills at
the mid flatters itself. ``price="BA"`` costs nothing extra and the stored
frame carries both sides plus the spread, which is the layout
:func:`~ict.data.loader.read_parquet` already understands.
"""

from __future__ import annotations

import os
import time as _time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import pandas as pd

from ..config import STORAGE_TZ

#: REST and streaming hosts. The only difference between practice and live.
REST_HOSTS = {
    "practice": "https://api-fxpractice.oanda.com",
    "live": "https://api-fxtrade.oanda.com",
}
STREAM_HOSTS = {
    "practice": "https://stream-fxpractice.oanda.com",
    "live": "https://stream-fxtrade.oanda.com",
}

#: The most candles OANDA will return in one response.
MAX_CANDLES = 5000

#: Granularities this module maps onto the project's timeframes.
GRANULARITIES = {"1m": "M1", "15m": "M15", "1h": "H1", "4h": "H4"}

_OHLC = ("o", "h", "l", "c")


class OandaError(RuntimeError):
    """An API call failed, or the environment is not configured."""


@dataclass(frozen=True)
class Credentials:
    """Everything needed to talk to one OANDA account."""

    token: str
    account_id: str = ""
    environment: str = "practice"

    @classmethod
    def from_env(cls) -> "Credentials":
        """Read credentials from the environment, or say what is missing.

        The account id is optional for downloading candles and required for
        anything that touches an account, so it is not checked here.
        """
        token = os.environ.get("OANDA_API_TOKEN", "").strip()
        if not token:
            raise OandaError(
                "OANDA_API_TOKEN is not set. Create a practice account at "
                "oanda.com, generate a token under Manage API Access, and "
                "export it. Never put it in the repository."
            )
        environment = os.environ.get("OANDA_ENVIRONMENT", "practice").strip().lower()
        if environment not in REST_HOSTS:
            raise OandaError(
                f"OANDA_ENVIRONMENT must be one of {sorted(REST_HOSTS)}, "
                f"got {environment!r}"
            )
        return cls(
            token=token,
            account_id=os.environ.get("OANDA_ACCOUNT_ID", "").strip(),
            environment=environment,
        )

    @property
    def is_live(self) -> bool:
        return self.environment == "live"


def _timestamp(value: str) -> pd.Timestamp:
    """OANDA's RFC3339 timestamps, which carry nanoseconds, as UTC."""
    return pd.Timestamp(value).tz_convert(STORAGE_TZ)


def _rfc3339(moment: pd.Timestamp) -> str:
    """A timestamp in the form OANDA's ``from`` and ``to`` parameters want."""
    moment = pd.Timestamp(moment)
    if moment.tz is None:
        moment = moment.tz_localize(STORAGE_TZ)
    return moment.tz_convert("UTC").strftime("%Y-%m-%dT%H:%M:%S.000000000Z")


class OandaClient:
    """A thin, retrying wrapper over the handful of endpoints this needs.

    ``session`` exists so the tests can drive the whole client against a fake
    transport. Nothing here touches the network unless a real session is
    handed in or built.
    """

    def __init__(
        self,
        credentials: Credentials | None = None,
        session=None,
        timeout: float = 30.0,
        max_attempts: int = 5,
    ) -> None:
        self.credentials = credentials or Credentials.from_env()
        self.timeout = timeout
        self.max_attempts = max_attempts
        if session is None:
            import requests

            session = requests.Session()
        self.session = session
        self.session.headers.update(
            {
                "Authorization": f"Bearer {self.credentials.token}",
                "Accept-Datetime-Format": "RFC3339",
                "Content-Type": "application/json",
            }
        )

    # --- plumbing ----------------------------------------------------------

    @property
    def rest_host(self) -> str:
        return REST_HOSTS[self.credentials.environment]

    @property
    def stream_host(self) -> str:
        return STREAM_HOSTS[self.credentials.environment]

    def _request(self, method: str, url: str, attempts: int | None = None, **kwargs):
        """One call, retried on the failures that are worth retrying.

        Rate limiting and server faults are transient and get exponential
        backoff. A 400 or a 401 is a bug or a bad token and retrying it just
        delays the error message.
        """
        delay = 1.0
        last: Exception | None = None
        max_attempts = self.max_attempts if attempts is None else attempts
        for attempt in range(1, max_attempts + 1):
            try:
                response = self.session.request(
                    method, url, timeout=self.timeout, **kwargs
                )
            except Exception as error:  # network level, always worth a retry
                last = error
                if attempt == max_attempts:
                    raise OandaError(f"{method} {url} failed: {error}") from error
                _time.sleep(delay)
                delay *= 2
                continue

            if response.status_code < 400:
                return response
            if response.status_code in (429, 500, 502, 503, 504):
                last = OandaError(f"{response.status_code} from {url}")
                if attempt == max_attempts:
                    break
                _time.sleep(delay)
                delay *= 2
                continue

            raise OandaError(
                f"{method} {url} returned {response.status_code}: "
                f"{_body(response)}"
            )

        raise OandaError(f"{method} {url} failed after {max_attempts} attempts: {last}")

    def get(self, path: str, params: dict | None = None) -> dict:
        response = self._request("GET", f"{self.rest_host}{path}", params=params)
        return response.json()

    def post(self, path: str, body: dict) -> dict:
        """A write. Never retried on a timeout, deliberately.

        A POST that creates an order is not idempotent: a request that timed
        out may still have reached the exchange, and retrying it can open two
        positions where the strategy asked for one. Only the transport level
        failures that provably did not arrive are retried, which is why writes
        go through with a single attempt and the caller reconciles.
        """
        response = self._request(
            "POST", f"{self.rest_host}{path}", json=body, attempts=1
        )
        return response.json()

    def put(self, path: str, body: dict) -> dict:
        """A write that names what it acts on, so repeating it is safe.

        Cancelling order 17 twice cancels order 17. The second call fails
        harmlessly, which is why these may be retried where a POST may not.
        """
        response = self._request("PUT", f"{self.rest_host}{path}", json=body)
        return response.json()

    # --- candles -----------------------------------------------------------

    def candle_page(
        self,
        instrument: str,
        start: pd.Timestamp,
        end: pd.Timestamp,
        granularity: str = "M1",
        count: int = MAX_CANDLES,
    ) -> list[dict]:
        """One page of candles, oldest first.

        ``includeFirst=false`` so a page never repeats the candle the previous
        page ended on.
        """
        payload = self.get(
            f"/v3/instruments/{instrument}/candles",
            params={
                "price": "BA",
                "granularity": granularity,
                "from": _rfc3339(start),
                "to": _rfc3339(end),
                "count": count,
                "includeFirst": "false",
                "smooth": "false",
            },
        )
        return payload.get("candles", [])

    def candles(
        self,
        instrument: str,
        start: pd.Timestamp,
        end: pd.Timestamp,
        granularity: str = "M1",
    ) -> Iterator[pd.DataFrame]:
        """Page through a whole range, yielding one frame per page.

        OANDA caps a response at 5,000 candles, so a year of 1 minute data is
        roughly seventy requests. Each page starts from the last candle of the
        one before, and the loop stops when a page comes back empty or stops
        advancing, which is what a weekend or a dead range looks like.
        """
        start = pd.Timestamp(start)
        end = pd.Timestamp(end)
        if start.tz is None:
            start = start.tz_localize(STORAGE_TZ)
        if end.tz is None:
            end = end.tz_localize(STORAGE_TZ)

        cursor = start - pd.Timedelta(seconds=1)  # includeFirst is false
        while cursor < end:
            page = self.candle_page(instrument, cursor, end, granularity)
            if not page:
                return
            last = _timestamp(page[-1]["time"])
            if last <= cursor:
                # The server repeated itself. Stop rather than loop for ever,
                # and do not hand the caller the same candles twice.
                return
            cursor = last
            frame = candles_to_frame(page)
            if not frame.empty:
                yield frame

    # --- streaming ---------------------------------------------------------

    def stream_prices(self, instruments: list[str]) -> Iterator[dict]:
        """Yield pricing messages as they arrive, for ever.

        Heartbeats are passed through rather than swallowed: a live runner
        needs them to tell a quiet market from a dead connection.
        """
        url = f"{self.stream_host}/v3/accounts/{self.account_id}/pricing/stream"
        response = self._request(
            "GET", url, params={"instruments": ",".join(instruments)}, stream=True
        )
        import json

        for line in response.iter_lines():
            if not line:
                continue
            try:
                yield json.loads(line)
            except ValueError:
                continue

    @property
    def account_id(self) -> str:
        if not self.credentials.account_id:
            raise OandaError(
                "OANDA_ACCOUNT_ID is not set, and this call needs an account."
            )
        return self.credentials.account_id


def _body(response) -> str:
    try:
        return str(response.json())
    except Exception:
        return getattr(response, "text", "")[:200]


def candles_to_frame(candles: list[dict]) -> pd.DataFrame:
    """Turn an OANDA candle list into the project's stored layout.

    Incomplete candles are dropped. A candle that is still forming has a high
    and a low that are not final, and treating one as closed is the same
    lookahead bug the whole timeframe stack exists to prevent. It matters live,
    where the newest candle is always incomplete, and in history when a
    download reaches the present minute.

    Prices arrive as strings so no precision is lost in OANDA's own JSON, and
    are converted once here.
    """
    rows = []
    for candle in candles:
        if not candle.get("complete", False):
            continue
        bid, ask = candle.get("bid"), candle.get("ask")
        if bid is None or ask is None:
            continue
        row: dict[str, object] = {"timestamp": _timestamp(candle["time"])}
        for side, prices in (("bid", bid), ("ask", ask)):
            for short, name in zip(_OHLC, ("open", "high", "low", "close")):
                row[f"{side}_{name}"] = float(prices[short])
        row["volume"] = float(candle.get("volume", 0))
        rows.append(row)

    columns = (
        ["timestamp"]
        + [f"{s}_{f}" for s in ("bid", "ask") for f in ("open", "high", "low", "close")]
        + ["volume"]
    )
    if not rows:
        return pd.DataFrame(columns=columns).set_index("timestamp")

    frame = pd.DataFrame(rows).set_index("timestamp").sort_index()
    for field in ("open", "high", "low", "close"):
        frame[f"mid_{field}"] = (frame[f"bid_{field}"] + frame[f"ask_{field}"]) / 2.0
    frame["spread"] = frame["ask_close"] - frame["bid_close"]
    return frame


def months(start: pd.Timestamp, end: pd.Timestamp) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """Split a range into calendar months, so a download is resumable.

    One file per month means an interrupted download resumes at the month it
    stopped on rather than starting again, which matters when a full history
    is several hundred requests.
    """
    start = pd.Timestamp(start).tz_convert(STORAGE_TZ).normalize().replace(day=1)
    end = pd.Timestamp(end).tz_convert(STORAGE_TZ)
    spans = []
    cursor = start
    while cursor < end:
        following = (cursor + pd.Timedelta(days=32)).normalize().replace(day=1)
        spans.append((cursor, min(following, end)))
        cursor = following
    return spans


def download(
    instrument: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
    directory: str | Path,
    client: OandaClient | None = None,
    granularity: str = "M1",
    on_progress=None,
) -> list[Path]:
    """Download a range month by month into ``directory``, skipping what is there.

    Returns every chunk file covering the range, downloaded or already
    present. The last month is always re-downloaded, because it may have been
    written before the month finished.
    """
    client = client or OandaClient()
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)

    spans = months(start, end)
    written: list[Path] = []
    for index, (span_start, span_end) in enumerate(spans):
        path = directory / f"{instrument}_{granularity}_{span_start:%Y-%m}.parquet"
        final_month = index == len(spans) - 1
        if path.exists() and not final_month:
            written.append(path)
            if on_progress:
                on_progress(path, None)
            continue

        pages = list(client.candles(instrument, span_start, span_end, granularity))
        frame = pd.concat(pages) if pages else pd.DataFrame()
        if frame.empty:
            if on_progress:
                on_progress(path, 0)
            continue
        frame = frame[~frame.index.duplicated(keep="last")].sort_index()
        frame.to_parquet(path, engine="pyarrow", index=True)
        written.append(path)
        if on_progress:
            on_progress(path, len(frame))
    return written


def combine(paths: list[Path]) -> pd.DataFrame:
    """Merge monthly chunks into one frame, de-duplicated and sorted."""
    frames = [pd.read_parquet(path, engine="pyarrow") for path in paths]
    frames = [f for f in frames if not f.empty]
    if not frames:
        return pd.DataFrame()
    frame = pd.concat(frames)
    frame.index = pd.DatetimeIndex(frame.index)
    if frame.index.tz is None:
        frame.index = frame.index.tz_localize(STORAGE_TZ)
    else:
        frame.index = frame.index.tz_convert(STORAGE_TZ)
    frame.index = frame.index.rename("timestamp")
    return frame[~frame.index.duplicated(keep="last")].sort_index()
