"""Fast "when did price first do X after here" queries.

Several detectors ask the same question thousands of times: given a level and a
starting candle, when did price first trade beyond that level? Answering it by
slicing the candle frame per level is O(levels x candles), which is tolerable on
a day of data and hopeless on the three years the validation gate calls for.

A max/min segment tree answers each query in O(log candles) by descending only
into the branches that could contain an answer, which turns the whole pass
linear-ish in the number of levels.
"""

from __future__ import annotations

import numpy as np

NOT_FOUND = -1


class _Tree:
    """Segment tree over a float array, supporting first-crossing queries."""

    def __init__(self, values: np.ndarray, maximum: bool) -> None:
        self.n = len(values)
        self.maximum = maximum
        self.size = 1
        while self.size < max(self.n, 1):
            self.size *= 2

        fill = -np.inf if maximum else np.inf
        self.tree = np.full(2 * self.size, fill, dtype="float64")
        if self.n:
            self.tree[self.size : self.size + self.n] = values

        combine = np.maximum if maximum else np.minimum
        for node in range(self.size - 1, 0, -1):
            self.tree[node] = combine(self.tree[2 * node], self.tree[2 * node + 1])

    def _promising(self, node: int, value: float) -> bool:
        """Could this subtree contain a crossing of ``value``?"""
        return (
            self.tree[node] > value if self.maximum else self.tree[node] < value
        )

    def first_crossing(self, start: int, value: float) -> int:
        """First index ``i >= start`` whose value crosses ``value``.

        For a max tree that means ``values[i] > value``; for a min tree,
        ``values[i] < value``. Returns :data:`NOT_FOUND` if there is none.
        """
        if start >= self.n or self.n == 0:
            return NOT_FOUND
        start = max(start, 0)
        return self._descend(1, 0, self.size - 1, start, value)

    def _descend(self, node: int, low: int, high: int, start: int, value: float) -> int:
        if high < start or not self._promising(node, value):
            return NOT_FOUND
        if low == high:
            return low if low < self.n else NOT_FOUND

        middle = (low + high) // 2
        found = self._descend(2 * node, low, middle, start, value)
        if found != NOT_FOUND:
            return found
        return self._descend(2 * node + 1, middle + 1, high, start, value)


class PriceScanner:
    """Crossing queries over one candle frame's highs, lows and closes."""

    def __init__(
        self, highs: np.ndarray, lows: np.ndarray, closes: np.ndarray
    ) -> None:
        self.highs = highs
        self.lows = lows
        self.closes = closes
        self._high_above = _Tree(highs, maximum=True)
        self._low_below = _Tree(lows, maximum=False)
        self._close_above = _Tree(closes, maximum=True)
        self._close_below = _Tree(closes, maximum=False)

    def first_high_above(self, start: int, level: float) -> int:
        return self._high_above.first_crossing(start, level)

    def first_low_below(self, start: int, level: float) -> int:
        return self._low_below.first_crossing(start, level)

    def first_close_above(self, start: int, level: float) -> int:
        return self._close_above.first_crossing(start, level)

    def first_close_below(self, start: int, level: float) -> int:
        return self._close_below.first_crossing(start, level)

    def first_traded_beyond(self, start: int, level: float, buy_side: bool) -> int:
        """First candle trading beyond ``level`` on the given side."""
        return (
            self.first_high_above(start, level)
            if buy_side
            else self.first_low_below(start, level)
        )

    def first_overlap(self, start: int, bottom: float, top: float) -> int:
        """First candle whose range overlaps the zone ``[bottom, top]``.

        Overlap is a conjunction, which a single tree cannot answer, so the
        tree supplies candidates on the binding side and each is checked. In
        practice the first candidate is almost always the answer.
        """
        position = start
        while True:
            # `nextafter` turns the tree's strict "below" into "at or below",
            # which a plain epsilon cannot do at forex price magnitudes.
            candidate = self.first_low_below(position, np.nextafter(top, np.inf))
            if candidate == NOT_FOUND:
                return NOT_FOUND
            if self.highs[candidate] >= bottom:
                return candidate
            position = candidate + 1
