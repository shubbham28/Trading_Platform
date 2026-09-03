"""
Shared helper for the sharpest causality question.

An equity-curve prefix comparison turns out to be too blunt. A strategy peeking
one bar ahead only decides differently on the truncated frame's final bar, and
that decision fills on the bar after it -- outside the compared prefix. So
`close.shift(-1)`, literal perfect foresight, sails through it.

The precise question is per-bar: given only bars 0..i, does the strategy make the
same decision the backtest attributes to bar i? Any k-bar peek fails this at
every bar, because a truncated frame ending at i has no bar i+1 to peek at.
"""
from typing import Optional

import pandas as pd

from app.session import build_contexts
from indicators import calculate_all_indicators
from strategies.base import BaseStrategy, Position, Signal


def decision_live(
    strategy: BaseStrategy,
    df: pd.DataFrame,
    i: int,
    timeframe: str,
    position: Optional[Position] = None,
) -> Signal:
    """The decision at bar i when nothing after bar i exists.

    This is the live case: the tape ends at the current bar.
    """
    frame = df.iloc[:i + 1].copy()
    prepared = strategy.prepare(calculate_all_indicators(frame))
    contexts = build_contexts(prepared, timeframe)
    return strategy.analyze(prepared, contexts[i], position)


def decision_backtest(
    strategy: BaseStrategy,
    df: pd.DataFrame,
    i: int,
    timeframe: str,
    position: Optional[Position] = None,
) -> Signal:
    """The decision at bar i when the whole series was available to `prepare`.

    This is the backtest case. It must agree with `decision_live`, or the
    backtested algorithm is not the one that would run.
    """
    prepared = strategy.prepare(calculate_all_indicators(df))
    contexts = build_contexts(prepared, timeframe)
    return strategy.analyze(prepared.iloc[:i + 1], contexts[i], position)


def synthetic_position(df: pd.DataFrame, i: int, lookback: int = 12) -> Position:
    """An open long entered `lookback` bars before bar i.

    Exit logic needs a position to reason about. Without one, only the entry half
    of every strategy would be under test -- and the flatten-by-close bug lived
    in the exit half.
    """
    entry_idx = max(0, i - lookback)
    entry = df.iloc[entry_idx]
    return Position(
        qty=10,
        entry_price=float(entry['close']),
        entry_time=entry['timestamp'],
    )
