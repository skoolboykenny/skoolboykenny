#!/usr/bin/env python3
"""Download 1 minute candles from Dukascopy in monthly chunks.

Runs the `dukascopy-node` CLI through `npx`, once per instrument, price type
and month, so a failure costs one month rather than the whole range. Chunks
already on disk are skipped, so re-running after a failure resumes rather than
restarting.

    python scripts/download_data.py                      # the full range
    python scripts/download_data.py --months 1           # one month, to check
    python scripts/download_data.py --dry-run            # print, run nothing

A chunk counts as downloaded only if its file exists **and is not empty**. The
CLI reports "File saved" and writes a zero byte file when it cannot reach the
data feed, so treating that as success would silently poison every later step.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"

INSTRUMENTS = ("eurusd", "gbpusd")
PRICE_TYPES = ("bid", "ask")
TIMEFRAME = "m1"
START = date(2021, 1, 1)

#: Retries here wrap whole chunks. The CLI's own -r retries individual
#: artifacts inside a chunk, which is a different failure and worth having too.
MAX_ATTEMPTS = 3
RETRY_PAUSE_SECONDS = 5
CLI_RETRIES = 3


@dataclass(frozen=True)
class Chunk:
    """One month of one instrument at one price type."""

    instrument: str
    price_type: str
    start: date
    end: date

    @property
    def directory(self) -> Path:
        return RAW / self.instrument / self.price_type

    @property
    def path(self) -> Path:
        """Where dukascopy-node will write this chunk."""
        return self.directory / (
            f"{self.instrument}-{TIMEFRAME}-{self.price_type}"
            f"-{self.start}-{self.end}.csv"
        )

    @property
    def label(self) -> str:
        return f"{self.instrument} {self.price_type} {self.start:%Y-%m}"

    def command(self) -> list[str]:
        return [
            "npx",
            "--yes",
            "dukascopy-node",
            "-i", self.instrument,
            "-from", str(self.start),
            "-to", str(self.end),
            "-t", TIMEFRAME,
            "-p", self.price_type,
            "-f", "csv",
            "-v",
            "-r", str(CLI_RETRIES),
            "-dir", str(self.directory),
        ]

    def is_downloaded(self) -> bool:
        """A chunk is only done if it has actual bytes in it."""
        return self.path.exists() and self.path.stat().st_size > 0


def month_starts(start: date, end: date) -> list[date]:
    """Every month boundary from ``start`` up to and including ``end``."""
    months = []
    current = date(start.year, start.month, 1)
    while current < end:
        months.append(current)
        current = (
            date(current.year + 1, 1, 1)
            if current.month == 12
            else date(current.year, current.month + 1, 1)
        )
    return months


def build_chunks(
    instruments: tuple[str, ...],
    price_types: tuple[str, ...],
    start: date,
    end: date,
    limit: int | None = None,
) -> list[Chunk]:
    """Every chunk to fetch, in a sensible order for resuming."""
    starts = month_starts(start, end)
    chunks: list[Chunk] = []
    for instrument in instruments:
        for price_type in price_types:
            for index, month in enumerate(starts):
                following = (
                    starts[index + 1] if index + 1 < len(starts) else end
                )
                chunks.append(Chunk(instrument, price_type, month, following))
    if limit is not None:
        # Take the first `limit` months of each instrument and price type, so
        # a trial run covers every combination rather than one instrument.
        trimmed: list[Chunk] = []
        seen: dict[tuple[str, str], int] = {}
        for chunk in chunks:
            key = (chunk.instrument, chunk.price_type)
            seen[key] = seen.get(key, 0) + 1
            if seen[key] <= limit:
                trimmed.append(chunk)
        chunks = trimmed
    return chunks


def download(chunk: Chunk, timeout: int) -> tuple[bool, str]:
    """Fetch one chunk, retrying a few times. Returns (ok, detail)."""
    chunk.directory.mkdir(parents=True, exist_ok=True)

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            result = subprocess.run(
                chunk.command(),
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=ROOT,
            )
        except subprocess.TimeoutExpired:
            detail = f"timed out after {timeout}s"
        else:
            if result.returncode != 0:
                detail = _last_line(result.stderr or result.stdout) or (
                    f"exit code {result.returncode}"
                )
            elif not chunk.is_downloaded():
                # The CLI exits 0 and writes an empty file when the data feed
                # is unreachable. Do not let that pass as a success.
                detail = "wrote an empty file (data feed unreachable?)"
                chunk.path.unlink(missing_ok=True)
            else:
                size = chunk.path.stat().st_size
                return True, f"{size:,} bytes"

        if attempt < MAX_ATTEMPTS:
            log(f"    attempt {attempt} failed: {detail}; retrying")
            time.sleep(RETRY_PAUSE_SECONDS * attempt)

    return False, detail


def _last_line(text: str) -> str:
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    return lines[-1] if lines else ""


def log(message: str) -> None:
    print(message, flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--instruments", nargs="*", default=list(INSTRUMENTS), choices=list(INSTRUMENTS)
    )
    parser.add_argument(
        "--price-types", nargs="*", default=list(PRICE_TYPES), choices=list(PRICE_TYPES)
    )
    parser.add_argument("--from", dest="start", default=str(START))
    parser.add_argument("--to", dest="end", default=str(date.today()))
    parser.add_argument(
        "--months",
        type=int,
        default=None,
        help="only the first N months of each instrument and price type",
    )
    parser.add_argument("--timeout", type=int, default=900, help="per chunk, seconds")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    chunks = build_chunks(
        tuple(args.instruments),
        tuple(args.price_types),
        date.fromisoformat(args.start),
        date.fromisoformat(args.end),
        limit=args.months,
    )

    pending = [c for c in chunks if not c.is_downloaded()]
    done = len(chunks) - len(pending)
    log(f"{len(chunks)} chunks, {done} already downloaded, {len(pending)} to fetch")

    if args.dry_run:
        for chunk in pending:
            log(f"  would run: {' '.join(chunk.command())}")
        return 0

    failures: list[tuple[Chunk, str]] = []
    for position, chunk in enumerate(pending, start=1):
        log(f"[{position}/{len(pending)}] {chunk.label}")
        ok, detail = download(chunk, args.timeout)
        if ok:
            log(f"    ok, {detail}")
        else:
            log(f"    FAILED: {detail}")
            failures.append((chunk, detail))

    log("")
    log(f"done: {len(pending) - len(failures)} fetched, {len(failures)} failed")
    if failures:
        log("\nfailed chunks (re-run this script to retry just these):")
        for chunk, detail in failures:
            log(f"  {chunk.label}: {detail}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
