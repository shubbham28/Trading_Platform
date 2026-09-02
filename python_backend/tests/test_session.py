"""
Session calendar tests.

The look-ahead defect lived here: "are we near the close?" was answered by
reading the dataset's length. These tests pin the calendar-derived replacement,
including the half-day case it cannot handle on its own.
"""
from datetime import date, time, timedelta

import pandas as pd
import pytest

from app.session import (
    DEFAULT_CLOSE, audit_early_close_risk, build_contexts, parse_bar_minutes,
)
from indicators import calculate_session_vwap, calculate_vwap
from tests.conftest import make_daily_bars, make_intraday_bars


def test_parse_bar_minutes():
    assert parse_bar_minutes('1Min') == 1
    assert parse_bar_minutes('5Min') == 5
    assert parse_bar_minutes('15Min') == 15
    assert parse_bar_minutes('1Hour') == 60
    assert parse_bar_minutes('2Hour') == 120
    assert parse_bar_minutes('1Day') is None
    assert parse_bar_minutes('1Week') is None


def test_unknown_timeframe_raises_rather_than_defaulting():
    """A silent default to daily would annualise minute bars as daily."""
    with pytest.raises(ValueError, match='Unrecognised timeframe'):
        parse_bar_minutes('every-so-often')


def test_one_context_per_bar():
    df = make_intraday_bars(n_sessions=3)
    assert len(build_contexts(df, '5Min')) == len(df)


def test_session_bar_index_restarts_each_session():
    df = make_intraday_bars(n_sessions=3, bar_minutes=5)
    contexts = build_contexts(df, '5Min')

    first_bars = [c for c in contexts if c.is_session_first_bar]
    assert len(first_bars) == 3, 'expected one first bar per session'
    assert all(c.session_bar_index == 0 for c in first_bars)

    # Within a session the index must increase by exactly one per bar.
    by_session = {}
    for c in contexts:
        by_session.setdefault(c.session_date, []).append(c.session_bar_index)
    for session_date, indices in by_session.items():
        assert indices == list(range(len(indices))), (
            f'session {session_date} bar indices are not contiguous from zero'
        )


def test_exactly_one_last_bar_per_session():
    """The flatten-by-close rule fires once a day, not on every bar.

    The old `index >= len(df) - 3` expression was true on three bars of the whole
    dataset in a backtest and on every bar live. This is the pinned replacement.
    """
    df = make_intraday_bars(n_sessions=4, bar_minutes=5)
    contexts = build_contexts(df, '5Min')

    per_session = {}
    for c in contexts:
        per_session.setdefault(c.session_date, []).append(c.is_session_last_bar)

    assert len(per_session) == 4
    for session_date, flags in per_session.items():
        assert sum(flags) == 1, (
            f'session {session_date} has {sum(flags)} bars marked as the last'
        )
        assert flags[-1] is True, 'the last bar of the session is not the flagged one'


def test_last_bar_flag_does_not_move_when_data_is_truncated():
    """The flag is a property of the clock, not of how much data follows."""
    full = make_intraday_bars(n_sessions=4, bar_minutes=5)
    short = full.iloc[:len(full) - 30].copy()

    full_flags = [c.is_session_last_bar for c in build_contexts(full, '5Min')]
    short_flags = [c.is_session_last_bar for c in build_contexts(short, '5Min')]

    assert short_flags == full_flags[:len(short_flags)]


def test_minutes_to_close_counts_down_within_a_session():
    df = make_intraday_bars(n_sessions=1, bar_minutes=5)
    contexts = build_contexts(df, '5Min')

    remaining = [c.minutes_to_close for c in contexts]
    assert remaining == sorted(remaining, reverse=True), 'not monotonically decreasing'
    assert remaining[0] == pytest.approx(390.0), 'first bar is not 390 minutes from close'
    assert remaining[-1] == pytest.approx(5.0), 'last bar is not one bar from close'

    opening = [c.minutes_since_open for c in contexts]
    assert opening[0] == pytest.approx(0.0)
    assert opening == sorted(opening)


def test_daily_bars_are_their_own_session():
    df = make_daily_bars(n=20)
    contexts = build_contexts(df, '1Day')

    assert all(c.is_session_first_bar and c.is_session_last_bar for c in contexts)
    assert all(c.minutes_to_close is None for c in contexts)
    assert all(not c.is_intraday for c in contexts)


def test_empty_frame_yields_no_contexts():
    assert build_contexts(pd.DataFrame({'timestamp': []}), '5Min') == []


def test_missing_timestamp_column_raises():
    with pytest.raises(ValueError, match='timestamp'):
        build_contexts(pd.DataFrame({'close': [1.0]}), '5Min')


# -- half-day handling ------------------------------------------------------

def _half_day_frame() -> pd.DataFrame:
    """One session whose tape stops at 13:00, as on a US equities half-day."""
    day = pd.Timestamp('2026-11-27')  # the Friday after Thanksgiving
    open_dt = day.replace(hour=9, minute=30)
    n_bars = (13 * 60 - (9 * 60 + 30)) // 5  # 09:30 to 13:00 in 5-minute bars
    timestamps = [open_dt + timedelta(minutes=5 * i) for i in range(n_bars)]
    return pd.DataFrame({
        'timestamp': timestamps,
        'open': [100.0] * n_bars, 'high': [100.5] * n_bars,
        'low': [99.5] * n_bars, 'close': [100.0] * n_bars,
        'volume': [1_000.0] * n_bars,
    })


def test_unhandled_half_day_is_detected_by_the_audit():
    """The known limitation fails loudly rather than silently.

    With no override, no bar of a 13:00 close satisfies `is_session_last_bar`, so
    a flatten-by-close rule never fires. That is a real gap; the point is that it
    is reported rather than quietly producing a wrong number.
    """
    df = _half_day_frame()
    contexts = build_contexts(df, '5Min')

    assert not any(c.is_session_last_bar for c in contexts), (
        'fixture no longer represents the unhandled half-day case'
    )
    assert audit_early_close_risk(df, '5Min') == [date(2026, 11, 27)]


def test_half_day_override_restores_the_last_bar_flag():
    df = _half_day_frame()
    overrides = {date(2026, 11, 27): time(13, 0)}

    contexts = build_contexts(df, '5Min', session_closes=overrides)
    flags = [c.is_session_last_bar for c in contexts]

    assert sum(flags) == 1
    assert flags[-1] is True
    assert audit_early_close_risk(df, '5Min', session_closes=overrides) == []


def test_audit_is_quiet_on_normal_sessions():
    assert audit_early_close_risk(make_intraday_bars(n_sessions=4), '5Min') == []


def test_audit_is_not_applicable_to_daily_data():
    assert audit_early_close_risk(make_daily_bars(n=30), '1Day') == []


# -- VWAP ------------------------------------------------------------------

def test_session_vwap_resets_each_session():
    """Defect 2. Cumulative VWAP over a multi-day frame is not VWAP."""
    df = make_intraday_bars(n_sessions=3, bar_minutes=5)
    session_vwap = calculate_session_vwap(df)
    cumulative = calculate_vwap(df)

    ts = pd.to_datetime(df['timestamp'])
    first_of_session = ts.groupby(ts.dt.date).transform('min') == ts

    # At each session's first bar, VWAP is that bar's typical price by
    # definition -- there is nothing else in the average yet.
    typical = (df['high'] + df['low'] + df['close']) / 3
    assert session_vwap[first_of_session].values == pytest.approx(
        typical[first_of_session].values
    )

    # From the second session onward the two must disagree, which is the bug.
    later = ~first_of_session & (ts.dt.date != ts.dt.date.min())
    assert not session_vwap[later].equals(cumulative[later])


def test_session_vwap_lies_between_session_low_and_high():
    """A volume-weighted average price cannot sit outside the session's range."""
    df = make_intraday_bars(n_sessions=3, bar_minutes=5)
    vwap = calculate_session_vwap(df)
    ts = pd.to_datetime(df['timestamp'])

    for session_date, idx in df.groupby(ts.dt.date).groups.items():
        rows = df.loc[idx]
        session_vwap = vwap.loc[idx].dropna()
        assert session_vwap.min() >= rows['low'].min() - 1e-9, session_date
        assert session_vwap.max() <= rows['high'].max() + 1e-9, session_date


def test_session_vwap_is_causal():
    """Removing later bars must not change an earlier VWAP value."""
    df = make_intraday_bars(n_sessions=4, bar_minutes=5)
    n = len(df) - 50
    full = calculate_session_vwap(df)
    truncated = calculate_session_vwap(df.iloc[:n].copy())
    assert full.iloc[:n].values == pytest.approx(truncated.values)


def test_session_vwap_requires_timestamps():
    df = make_intraday_bars(n_sessions=1).drop(columns=['timestamp'])
    with pytest.raises(ValueError, match='timestamp'):
        calculate_session_vwap(df)
