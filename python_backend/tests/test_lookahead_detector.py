"""
Tests for the look-ahead tests.

A green causality suite means nothing until the suite is shown to fail on code
that actually cheats. These canaries reintroduce each original defect in a
throwaway strategy and assert the check rejects it. If a canary ever passes, the
corresponding guarantee in test_no_lookahead.py has stopped holding and every
backtest number is unverified again.
"""
from typing import Optional

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal, assert_series_equal

from app.backtest import BacktestConfig, BacktestEngine
from indicators import calculate_all_indicators
from strategies.base import BarContext, BaseStrategy, Position, Signal
from tests._causality import (
    decision_backtest, decision_live, synthetic_position,
)
from tests.conftest import make_intraday_bars


class DatasetLengthCheat(BaseStrategy):
    """The original defect: end-of-day derived from the dataset's length.

    `index >= len(df) - 3` in the old code. Here the window is already truncated
    to the current bar, so the equivalent cheat has to look at the frame handed
    to `prepare`, which does span the whole run.
    """

    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        # Reads the total row count: the value at bar i changes if bars are
        # added or removed after i.
        df['_near_end'] = df.index >= (len(df) - 3)
        return df

    def analyze(self, window, ctx, position):
        now = window.iloc[-1]
        action = 'sell' if now['_near_end'] and position else 'hold'
        if position is None and ctx.session_bar_index == 5:
            action = 'buy'
        return Signal(
            timestamp=ctx.timestamp, action=action, confidence=0.5,
            reason='canary', price=float(now['close']),
        )


class FutureWindowCheat(BaseStrategy):
    """Normalises every bar against the series' final close.

    Uses `.iloc[-1]` rather than `.max()`: a global maximum is only non-causal
    when it happens to sit in the tail, and on this fixture it did not, so the
    first version of this canary was not actually cheating. The last close
    always changes when the frame is resized.
    """

    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df['_normalised'] = df['close'] / df['close'].iloc[-1]
        return df

    def analyze(self, window, ctx, position):
        now = window.iloc[-1]
        want_long = now['_normalised'] < 1.0
        if position is None and want_long:
            action = 'buy'
        elif position is not None and not want_long:
            action = 'sell'
        else:
            action = 'hold'
        return Signal(
            timestamp=ctx.timestamp, action=action, confidence=0.5,
            reason='canary', price=float(now['close']),
        )


class CentredWindowCheat(BaseStrategy):
    """A centred rolling mean: bar i's value is built from bars after i."""

    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df['_centred'] = df['close'].rolling(11, center=True, min_periods=1).mean()
        return df

    def analyze(self, window, ctx, position):
        # Symmetric entry and exit. A buy-once strategy hides the cheat: both
        # runs enter on the same early bar and the curves agree regardless of
        # what the centred mean does near the tail.
        now = window.iloc[-1]
        above = now['close'] > now['_centred']
        if position is None and above:
            action = 'buy'
        elif position is not None and not above:
            action = 'sell'
        else:
            action = 'hold'
        return Signal(
            timestamp=ctx.timestamp, action=action, confidence=0.5,
            reason='canary', price=float(now['close']),
        )


class FutureShiftCheat(BaseStrategy):
    """Perfect foresight: reads the next bar's close."""

    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df['_next_close'] = df['close'].shift(-1)
        return df

    def analyze(self, window, ctx, position):
        now = window.iloc[-1]
        if pd.isna(now['_next_close']):
            return self.hold(window, ctx, 'canary')
        going_up = now['_next_close'] > now['close']
        if position is None and going_up:
            action = 'buy'
        elif position is not None and not going_up:
            action = 'sell'
        else:
            action = 'hold'
        return Signal(
            timestamp=ctx.timestamp, action=action, confidence=0.5,
            reason='canary', price=float(now['close']),
        )


# Every cheat must be caught at the indicator level.
PREPARE_CHEATS = [
    DatasetLengthCheat, FutureWindowCheat, CentredWindowCheat, FutureShiftCheat,
]

# The end-to-end equity-curve check has a known blind spot, established by
# running these canaries against it rather than assumed:
#
#   * CentredWindowCheat -- distortion confined to the last few bars, too small
#     on this fixture to flip `close > centred` into a different decision.
#   * FutureShiftCheat -- a one-bar peek changes the decision only on the
#     truncated frame's final bar, and that decision fills on the bar after it,
#     outside the compared prefix.
#
# Both are caught by the per-bar check at the bottom of this file, which is
# therefore the guarantee to rely on. The equity-curve check is kept because it
# tests the whole pipeline end to end, not because it is sufficient. A suite
# built on it alone would certify `close.shift(-1)` as causal.
SIGNAL_CHEATS = [DatasetLengthCheat, FutureWindowCheat]

TRUNCATE = 40


@pytest.mark.parametrize('cheat_class', PREPARE_CHEATS, ids=lambda c: c.__name__)
def test_prepare_causality_check_rejects_cheating(cheat_class):
    """The indicator-level check must fail on a non-causal `prepare`."""
    df = make_intraday_bars()
    strategy = cheat_class()

    full = strategy.prepare(calculate_all_indicators(df))
    n = len(df) - TRUNCATE
    truncated = strategy.prepare(calculate_all_indicators(df.iloc[:n].copy()))

    cheat_column = [c for c in truncated.columns if c.startswith('_')][0]
    with pytest.raises(AssertionError):
        assert_series_equal(
            full[cheat_column].iloc[:n].reset_index(drop=True),
            truncated[cheat_column].reset_index(drop=True),
            check_names=False,
        )


@pytest.mark.parametrize('cheat_class', SIGNAL_CHEATS, ids=lambda c: c.__name__)
def test_signal_causality_check_rejects_cheating(cheat_class):
    """The end-to-end check must fail on a cheating strategy.

    This is the one that matters. An indicator can be non-causal in a way that
    never reaches a decision; a divergent equity curve means the cheat changed
    what the strategy actually did.
    """
    df = make_intraday_bars()
    n = len(df) - TRUNCATE

    def run(frame):
        return BacktestEngine(
            BacktestConfig(
                symbol='TEST', start_date='2026-01-01', end_date='2026-12-31',
                strategy_id='canary', timeframe='5Min',
            ),
            cheat_class(),
        ).run(frame)

    full_curve = pd.DataFrame(run(df).equity_curve).iloc[:n].reset_index(drop=True)
    trunc_curve = pd.DataFrame(run(df.iloc[:n].copy()).equity_curve).reset_index(drop=True)

    with pytest.raises(AssertionError):
        assert_frame_equal(full_curve, trunc_curve)


class StatefulCheat(BaseStrategy):
    """Holds its own position flag, the way the original strategies did."""

    def _initialize(self):
        self.position_open = False
        self.entry_price = None

    def analyze(self, window, ctx, position):
        return self.hold(window, ctx, 'canary')


def test_state_check_rejects_strategy_held_position():
    """The statelessness check must fail on a strategy holding a position flag."""
    strategy = StatefulCheat()
    forbidden = {'position_open', 'entry_price', 'highest_price',
                 'opening_range_high', 'opening_range_low', 'opening_range_set',
                 'sector_selected'}
    assert forbidden.intersection(vars(strategy)), (
        'the statelessness check no longer detects strategy-held position state'
    )


@pytest.mark.parametrize('cheat_class', PREPARE_CHEATS, ids=lambda c: c.__name__)
def test_per_bar_check_rejects_every_cheat(cheat_class):
    """The per-bar check must reject all four cheats, including the 1-bar peek.

    The reason this test exists: `FutureShiftCheat` -- `close.shift(-1)`, perfect
    foresight -- passes the equity-curve prefix comparison. A one-bar peek only
    changes the decision on the truncated frame's final bar, and that decision
    fills on the bar after it, outside the compared prefix. The per-bar check has
    no such blind spot, so it is the guarantee worth relying on.
    """
    df = make_intraday_bars()
    strategy = cheat_class()

    disagreements = 0
    for i in range(30, len(df), 29):
        for position in (None, synthetic_position(df, i)):
            live = decision_live(strategy, df, i, '5Min', position)
            backtest = decision_backtest(strategy, df, i, '5Min', position)
            if (live.action, live.reason) != (backtest.action, backtest.reason):
                disagreements += 1

    assert disagreements > 0, (
        f'{cheat_class.__name__} reads the future but the per-bar check did not '
        'notice. The causality guarantee in test_no_lookahead.py is unsound.'
    )
