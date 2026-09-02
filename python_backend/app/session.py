"""
Session calendar.

Turns a bar series into per-bar `BarContext` objects. Every field is derived
from the bar's own timestamp plus the exchange session times -- never from how
many bars follow it. That distinction is the whole reason this module exists:
the previous implementation asked `index >= len(df) - 3` to decide "are we near
the close?", which is a reading of the dataset's length. Live, that expression
is true on every bar, so the backtested algorithm and the live algorithm were
not the same algorithm.

KNOWN LIMITATION -- early closes. US equities close at 13:00 ET on roughly nine
half-days a year (the day after Thanksgiving, Christmas Eve, and similar). This
module assumes a 16:00 close unless told otherwise. On a half-day, a strategy
relying on `minutes_to_close` will believe it has three more hours than it does
and will not flatten before the bell. Two ways to be correct:

  * pass `session_closes={date(2026, 11, 27): time(13, 0), ...}`, or
  * install `exchange_calendars` and source the overrides from it (Phase 2).

The failure is loud rather than silent: `audit_early_close_risk` reports any
session whose last observed bar sits well before the assumed close, which is
exactly the fingerprint of an unhandled half-day.
"""
import re
from datetime import date, time
from typing import Dict, List, Optional

import pandas as pd

from strategies.base import BarContext

# US equities regular session, in exchange-local time.
DEFAULT_OPEN = time(9, 30)
DEFAULT_CLOSE = time(16, 0)
EXCHANGE_TZ = "America/New_York"

_TIMEFRAME_RE = re.compile(r'^(\d+)(Min|Hour|Day|Week|Month)$')


def parse_bar_minutes(timeframe: str) -> Optional[int]:
    """Bar length in minutes, or None for daily and coarser.

    None is meaningful, not an error: on a daily series each bar *is* a
    session, so intraday concepts like "minutes to close" do not apply.
    """
    match = _TIMEFRAME_RE.match(timeframe)
    if not match:
        raise ValueError(
            f"Unrecognised timeframe {timeframe!r}. "
            "Expected e.g. '1Min', '5Min', '15Min', '1Hour', '1Day'."
        )
    amount, unit = int(match.group(1)), match.group(2)
    if unit == 'Min':
        return amount
    if unit == 'Hour':
        return amount * 60
    return None  # Day, Week, Month -- one bar per session or longer


def build_contexts(
    df: pd.DataFrame,
    timeframe: str,
    session_closes: Optional[Dict[date, time]] = None,
    tz: str = EXCHANGE_TZ,
) -> List[BarContext]:
    """Build one BarContext per row of `df`.

    Args:
        df: bars with a 'timestamp' column, ascending.
        timeframe: e.g. '5Min', '1Day'.
        session_closes: per-date close overrides for half-days.
        tz: exchange timezone for session bucketing.

    Returns:
        A list the same length as `df`, aligned by position.
    """
    if 'timestamp' not in df.columns:
        raise ValueError("df must have a 'timestamp' column")
    if df.empty:
        return []

    bar_minutes = parse_bar_minutes(timeframe)
    is_intraday = bar_minutes is not None
    overrides = session_closes or {}

    ts = pd.to_datetime(df['timestamp'])
    # Bars may arrive tz-aware (Alpaca sends UTC) or naive. Naive timestamps are
    # assumed to already be exchange-local, which is the only assumption that
    # does not silently shift a 09:30 bar into the previous session.
    local = ts.dt.tz_convert(tz) if ts.dt.tz is not None else ts

    session_dates = local.dt.date
    # cumcount over the session gives "how many bars of this session have I
    # already seen", which is causal: it never consults later rows.
    session_bar_index = local.groupby(session_dates).cumcount()

    contexts: List[BarContext] = []
    for i in range(len(df)):
        bar_ts = local.iloc[i]
        session_date = session_dates.iloc[i]
        bar_index_in_session = int(session_bar_index.iloc[i])

        if not is_intraday:
            # A daily bar is its own session: it is simultaneously the first and
            # last bar, and minutes-to-close is not a meaningful quantity.
            contexts.append(BarContext(
                index=i,
                timestamp=bar_ts,
                session_date=session_date,
                session_bar_index=0,
                minutes_since_open=None,
                minutes_to_close=None,
                is_session_first_bar=True,
                is_session_last_bar=True,
                is_intraday=False,
                bar_minutes=None,
            ))
            continue

        close_time = overrides.get(session_date, DEFAULT_CLOSE)
        open_dt = bar_ts.normalize() + pd.Timedelta(
            hours=DEFAULT_OPEN.hour, minutes=DEFAULT_OPEN.minute
        )
        close_dt = bar_ts.normalize() + pd.Timedelta(
            hours=close_time.hour, minutes=close_time.minute
        )

        minutes_since_open = (bar_ts - open_dt).total_seconds() / 60.0
        minutes_to_close = (close_dt - bar_ts).total_seconds() / 60.0

        # A bar labelled by its opening time is the session's last when there is
        # no room for another full bar before the bell. Derived from the clock,
        # so it is true at the same moment live.
        is_last = minutes_to_close <= bar_minutes

        contexts.append(BarContext(
            index=i,
            timestamp=bar_ts,
            session_date=session_date,
            session_bar_index=bar_index_in_session,
            minutes_since_open=minutes_since_open,
            minutes_to_close=minutes_to_close,
            is_session_first_bar=bar_index_in_session == 0,
            is_session_last_bar=is_last,
            is_intraday=True,
            bar_minutes=bar_minutes,
        ))

    return contexts


def audit_early_close_risk(
    df: pd.DataFrame,
    timeframe: str,
    session_closes: Optional[Dict[date, time]] = None,
    tz: str = EXCHANGE_TZ,
    tolerance_minutes: int = 60,
) -> List[date]:
    """Sessions whose data ends well before the assumed close.

    An unhandled half-day looks exactly like this: the tape stops at 13:00 while
    the calendar still thinks the close is 16:00, so no bar ever satisfies
    `is_session_last_bar` and a flatten-by-close rule never fires. Call this
    before trusting a backtest and pass anything it returns back in as a
    `session_closes` override.

    Returns dates needing an override, empty when the calendar and the data
    agree. Only meaningful for intraday data; daily data returns empty.
    """
    bar_minutes = parse_bar_minutes(timeframe)
    if bar_minutes is None or df.empty:
        return []

    overrides = session_closes or {}
    ts = pd.to_datetime(df['timestamp'])
    local = ts.dt.tz_convert(tz) if ts.dt.tz is not None else ts

    suspect: List[date] = []
    for session_date, group in local.groupby(local.dt.date):
        last_bar = group.max()
        close_time = overrides.get(session_date, DEFAULT_CLOSE)
        close_dt = last_bar.normalize() + pd.Timedelta(
            hours=close_time.hour, minutes=close_time.minute
        )
        gap_minutes = (close_dt - last_bar).total_seconds() / 60.0
        if gap_minutes > tolerance_minutes:
            suspect.append(session_date)

    return suspect
