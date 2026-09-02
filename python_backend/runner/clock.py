"""
Bar clocks.

A clock's only job is to say "here is the history up to and including a bar that
has just completed". The runner does everything else, so it cannot tell whether
it is being driven by a replay or by a live feed -- which is what lets the same
runner be tested deterministically and then run for real.

TWO IMPLEMENTATIONS, NOT THREE.

The plan listed a DailyClock polling once per session close and an IntradayClock
reading a websocket. Both are the same thing: wake on a schedule, ask the data
provider what has completed since last time. So there is one `PollingClock`
parameterised by timeframe, and a daily bot is simply one whose bar is a session.
Two classes where one parameterised class does the job is two places for a bug.

The websocket is deliberately not here. It is a latency optimisation -- Alpaca's
bars endpoint already returns completed minute bars -- and a websocket client
that cannot be tested against a live feed is exactly the code that ships broken.
Recorded in TODOS.md as a deferred optimisation with that reasoning, not dropped.

BARS MUST BE COMPLETE. A clock never emits the bar currently forming. Acting on
a partial bar means the close a strategy reasoned about was not the close, so
live behaviour would diverge from every backtest for a reason no test could
catch.
"""
import time as time_module
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterator, Optional

import pandas as pd

from app.session import parse_bar_minutes
from data.base import DataProvider


@dataclass(frozen=True)
class BarEvent:
    """One completed bar, with the history leading up to it.

    `bars` ends at the bar that just completed and contains nothing after it.
    The runner hands it straight to the strategy, so the causality guarantee from
    Phase 1 holds live for the same structural reason it holds in backtest:
    future bars are absent, not merely off limits.
    """
    symbol: str
    bars: pd.DataFrame
    timestamp: pd.Timestamp

    @property
    def bar_index(self) -> int:
        return len(self.bars) - 1


class BarClock(ABC):
    """Emits completed bars for one symbol."""

    symbol: str
    timeframe: str

    @abstractmethod
    def ticks(self) -> Iterator[BarEvent]:
        """Yield bar events until the clock decides it is done."""
        raise NotImplementedError


class HistoricalClock(BarClock):
    """Replays a stored frame, one bar at a time.

    This is what makes the runner testable, and more than that: driving the
    runner from a replay of the same bars the backtester saw is how the
    architecture's central claim gets checked. If the runner and the backtester
    reach different decisions on identical input, one of them is wrong, and
    `test_runner_matches_backtester` fails.
    """

    def __init__(
        self,
        symbol: str,
        bars: pd.DataFrame,
        timeframe: str = '1Day',
        start_index: int = 0,
    ):
        self.symbol = symbol
        self.timeframe = timeframe
        self.bars = bars.reset_index(drop=True)
        self.start_index = start_index

    def ticks(self) -> Iterator[BarEvent]:
        for i in range(self.start_index, len(self.bars)):
            window = self.bars.iloc[:i + 1]
            yield BarEvent(
                symbol=self.symbol,
                bars=window,
                timestamp=pd.Timestamp(window.iloc[-1]['timestamp']),
            )


class PollingClock(BarClock):
    """Fetches completed bars from a DataProvider on a schedule.

    Serves both roles from the plan. An intraday bot polls every `bar_minutes`;
    a daily bot's bar is the whole session, so it polls once the session has
    closed. The difference is the timeframe, not the mechanism.

    Only bars strictly newer than the last one emitted are yielded, so a poll
    that returns overlapping history -- which providers do -- cannot replay a bar
    the runner has already acted on.
    """

    # How long after a bar's period ends before asking for it. Providers do not
    # publish a bar the instant its period closes, and asking too early returns
    # either nothing or a partial bar.
    SETTLE_SECONDS = 15

    def __init__(
        self,
        symbol: str,
        provider: DataProvider,
        timeframe: str = '5Min',
        lookback_days: int = 10,
        max_ticks: Optional[int] = None,
        sleeper=time_module.sleep,
        now=lambda: datetime.now(timezone.utc),
    ):
        self.symbol = symbol
        self.provider = provider
        self.timeframe = timeframe
        self.bar_minutes = parse_bar_minutes(timeframe)
        self.lookback_days = lookback_days
        # Bounded runs for tests and for a single session. None means run until
        # the process is stopped.
        self.max_ticks = max_ticks
        # Injected so tests do not actually wait, and so a fake clock can drive
        # a whole session in milliseconds.
        self._sleep = sleeper
        self._now = now
        self._last_emitted: Optional[pd.Timestamp] = None

    def _poll_interval_seconds(self) -> int:
        if self.bar_minutes is None:
            # Daily: there is one bar per session, so there is no point polling
            # more than a few times an hour waiting for it.
            return 900
        return self.bar_minutes * 60

    def _fetch(self) -> pd.DataFrame:
        end = self._now()
        start = end - timedelta(days=self.lookback_days)
        return self.provider.get_bars(
            self.symbol, start.isoformat(), end.isoformat(), self.timeframe
        )

    def ticks(self) -> Iterator[BarEvent]:
        emitted = 0
        while self.max_ticks is None or emitted < self.max_ticks:
            frame = self._fetch()

            if not frame.empty:
                stamps = pd.to_datetime(frame['timestamp'])
                if self._last_emitted is None:
                    new_positions = [len(frame) - 1]
                else:
                    new_positions = [
                        i for i in range(len(frame))
                        if stamps.iloc[i] > self._last_emitted
                    ]

                for i in new_positions:
                    window = frame.iloc[:i + 1]
                    stamp = pd.Timestamp(stamps.iloc[i])
                    self._last_emitted = stamp
                    emitted += 1
                    yield BarEvent(
                        symbol=self.symbol, bars=window, timestamp=stamp
                    )
                    if self.max_ticks is not None and emitted >= self.max_ticks:
                        return

            self._sleep(self._poll_interval_seconds())
