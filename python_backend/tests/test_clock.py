"""
Clock tests.

The clock's contract is narrow and load-bearing: emit each completed bar exactly
once, with the history up to it and nothing after it. Both halves matter -- a
duplicated bar means a duplicated decision, and a partial bar means the close a
strategy reasoned about was not the close.
"""
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from runner.clock import HistoricalClock, PollingClock
from tests.conftest import make_daily_bars, make_intraday_bars
from tests.test_interfaces import FakeDataProvider


class StopTest(Exception):
    """Breaks out of an unbounded clock.

    Not StopIteration: PEP 479 turns a StopIteration raised inside a generator
    into a RuntimeError, so using it as a break signal tests the wrong thing.
    """


# -- HistoricalClock -------------------------------------------------------

def test_historical_clock_emits_every_bar_once():
    bars = make_daily_bars(n=30)
    events = list(HistoricalClock('TEST', bars, '1Day').ticks())

    assert len(events) == len(bars)
    assert [e.timestamp for e in events] == list(pd.to_datetime(bars['timestamp']))


def test_historical_clock_window_ends_at_the_current_bar():
    """No future bars in the window, structurally.

    This is what carries the Phase 1 causality guarantee into live running: the
    strategy cannot read ahead because there is nothing ahead to read.
    """
    bars = make_daily_bars(n=20)
    for i, event in enumerate(HistoricalClock('TEST', bars, '1Day').ticks()):
        assert len(event.bars) == i + 1
        assert event.bars.iloc[-1]['timestamp'] == bars.iloc[i]['timestamp']
        assert event.bar_index == i


def test_historical_clock_can_start_partway_through():
    """Skipping warmup bars when a session resumes mid-stream."""
    bars = make_daily_bars(n=20)
    events = list(HistoricalClock('TEST', bars, '1Day', start_index=15).ticks())

    assert len(events) == 5
    # The window still carries the full history, only the emission starts later.
    assert len(events[0].bars) == 16


def test_historical_clock_on_an_empty_frame_emits_nothing():
    assert list(HistoricalClock('TEST', pd.DataFrame(), '1Day').ticks()) == []


# -- PollingClock ----------------------------------------------------------

class StepProvider(FakeDataProvider):
    """Reveals one more bar of a fixed frame on each call.

    Models what a real provider does as a session progresses: the same request
    returns a longer frame each time, overlapping everything already seen.
    """

    def __init__(self, frame, first: int = 1):
        super().__init__(frame)
        self.full = frame
        self.revealed = first

    def get_bars(self, symbol, start_date, end_date, timeframe='1Day'):
        out = self.full.iloc[:self.revealed]
        self.revealed = min(self.revealed + 1, len(self.full))
        return out


def test_polling_clock_emits_each_new_bar_once():
    """Overlapping history must not replay bars already acted on."""
    bars = make_intraday_bars(n_sessions=1, bar_minutes=5).iloc[:10]
    clock = PollingClock(
        'TEST', StepProvider(bars), '5Min', max_ticks=9, sleeper=lambda s: None
    )
    events = list(clock.ticks())

    stamps = [e.timestamp for e in events]
    assert len(stamps) == len(set(stamps)), 'a bar was emitted twice'
    assert stamps == sorted(stamps), 'bars arrived out of order'


def test_polling_clock_starts_from_the_latest_bar_not_the_whole_history():
    """A fresh clock must not replay a week of history as if it were live.

    Emitting everything the first poll returns would have the bot act on every
    bar of the lookback window in the space of a second.
    """
    bars = make_intraday_bars(n_sessions=2, bar_minutes=5)
    provider = FakeDataProvider(bars)
    clock = PollingClock(
        'TEST', provider, '5Min', max_ticks=1, sleeper=lambda s: None
    )
    events = list(clock.ticks())

    assert len(events) == 1
    assert events[0].timestamp == pd.Timestamp(bars.iloc[-1]['timestamp'])


def test_polling_clock_respects_max_ticks():
    bars = make_intraday_bars(n_sessions=1, bar_minutes=5)
    clock = PollingClock(
        'TEST', StepProvider(bars, first=1), '5Min', max_ticks=3,
        sleeper=lambda s: None,
    )
    assert len(list(clock.ticks())) == 3


def test_polling_clock_sleeps_for_one_bar_period():
    """Polling far more often than bars complete is wasted requests."""
    slept = []

    def sleeper(seconds):
        slept.append(seconds)
        raise StopTest

    clock = PollingClock(
        'TEST', FakeDataProvider(pd.DataFrame()), '5Min', sleeper=sleeper
    )
    with pytest.raises(StopTest):
        list(clock.ticks())
    assert slept == [300], f'expected a 300s poll interval, got {slept}'


def test_polling_clock_daily_timeframe_polls_less_often():
    """One bar per session means no point waking every five minutes."""
    clock = PollingClock('TEST', FakeDataProvider(), '1Day')
    assert clock.bar_minutes is None
    assert clock._poll_interval_seconds() == 900


def test_polling_clock_tolerates_an_empty_response():
    """Before the open, a provider legitimately has nothing to return."""
    slept = []

    def sleeper(seconds):
        slept.append(seconds)
        if len(slept) >= 3:
            raise StopTest

    clock = PollingClock(
        'TEST', FakeDataProvider(pd.DataFrame()), '5Min', sleeper=sleeper
    )
    with pytest.raises(StopTest):
        list(clock.ticks())
    assert len(slept) == 3, 'the clock stopped polling instead of waiting'


def test_polling_clock_rejects_an_unparseable_timeframe():
    """A silent default to daily would poll once every fifteen minutes for
    minute bars and look like a dead feed."""
    with pytest.raises(ValueError, match='Unrecognised timeframe'):
        PollingClock('TEST', FakeDataProvider(), 'sometimes')
