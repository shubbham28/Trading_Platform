"""
Synthetic market data for tests.

Real market data would make these tests depend on a network call, an API key,
and a vendor's idea of history. Synthetic data is generated from a fixed seed,
so a failure is always reproducible and always the code's fault.

The generators deliberately produce bars that trigger the strategies: overnight
gaps large enough to clear a 2% threshold, volume spikes that clear a 2x surge
filter, and both trending and mean-reverting stretches. A causality test over
data that never trades proves nothing.
"""
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytest

SESSION_OPEN_HOUR, SESSION_OPEN_MIN = 9, 30
SESSION_CLOSE_HOUR = 16


def _bar_extremes(bar_open: float, bar_close: float, rng) -> tuple:
    """High and low around one bar's open and close.

    Drawn per bar rather than in one array at the end, so that generating N
    sessions yields a true prefix of generating N+k sessions. Batching the draws
    made every high and low depend on the total frame length, which broke the
    prefix property the padding test relies on.
    """
    spread = abs(bar_close) * rng.uniform(0.0005, 0.004)
    return max(bar_open, bar_close) + spread, min(bar_open, bar_close) - spread


def make_intraday_bars(
    n_sessions: int = 6,
    bar_minutes: int = 5,
    start_date: str = '2026-03-02',  # a Monday
    seed: int = 7,
    start_price: float = 100.0,
) -> pd.DataFrame:
    """Minute-family bars across several regular sessions.

    Timestamps are tz-naive and exchange-local, which is how `build_contexts`
    treats naive input.
    """
    rng = np.random.default_rng(seed)
    bars_per_session = ((SESSION_CLOSE_HOUR * 60) - (SESSION_OPEN_HOUR * 60 + SESSION_OPEN_MIN)) // bar_minutes

    timestamps, opens, closes, highs, lows, volumes = [], [], [], [], [], []
    price = start_price
    day = pd.Timestamp(start_date)

    for session in range(n_sessions):
        # Skip weekends so sessions land on real weekdays.
        while day.weekday() >= 5:
            day += timedelta(days=1)

        # Overnight gap. Every third session gaps up hard enough to clear a 2%
        # gap filter, so the morning-momentum path is actually exercised.
        gap = 0.025 + rng.uniform(0, 0.01) if session % 3 == 1 else rng.normal(0, 0.004)
        price *= (1 + gap)

        # Alternate trending and mean-reverting sessions.
        drift = 0.0004 if session % 2 == 0 else -0.0003
        session_open = day.replace(
            hour=SESSION_OPEN_HOUR, minute=SESSION_OPEN_MIN, second=0, microsecond=0
        )

        for b in range(bars_per_session):
            bar_open = price
            step = rng.normal(drift, 0.0016)
            price = max(price * (1 + step), 1.0)
            # Volume is heavy at the open and spikes periodically, so the 2x
            # surge filters have something to fire on.
            base = rng.lognormal(mean=10.5, sigma=0.25)
            if b < 3:
                base *= 3.0
            elif b % 17 == 0:
                base *= 2.8
            high, low = _bar_extremes(bar_open, price, rng)

            timestamps.append(session_open + timedelta(minutes=bar_minutes * b))
            opens.append(bar_open)
            closes.append(price)
            highs.append(high)
            lows.append(low)
            volumes.append(float(base))

        day += timedelta(days=1)

    return pd.DataFrame({
        'timestamp': timestamps,
        'open': np.array(opens),
        'high': np.array(highs),
        'low': np.array(lows),
        'close': np.array(closes),
        'volume': np.array(volumes),
    })


def make_daily_bars(
    n: int = 260, start_date: str = '2025-01-02', seed: int = 11,
    start_price: float = 100.0,
) -> pd.DataFrame:
    """Daily bars with alternating trend regimes, so crossovers actually occur."""
    rng = np.random.default_rng(seed)
    timestamps, opens, closes, highs, lows, volumes = [], [], [], [], [], []
    price = start_price
    day = pd.Timestamp(start_date)

    for i in range(n):
        while day.weekday() >= 5:
            day += timedelta(days=1)
        # Regime flips every 40 bars so moving averages cross repeatedly.
        drift = 0.004 if (i // 40) % 2 == 0 else -0.0035
        bar_open = price
        price = max(price * (1 + rng.normal(drift, 0.011)), 1.0)
        volume = float(rng.lognormal(mean=13.0, sigma=0.3))
        high, low = _bar_extremes(bar_open, price, rng)

        timestamps.append(day)
        opens.append(bar_open)
        closes.append(price)
        highs.append(high)
        lows.append(low)
        volumes.append(volume)
        day += timedelta(days=1)

    return pd.DataFrame({
        'timestamp': timestamps,
        'open': np.array(opens),
        'high': np.array(highs),
        'low': np.array(lows),
        'close': np.array(closes),
        'volume': np.array(volumes),
    })


def make_flat_bars(n: int = 40, price: float = 50.0) -> pd.DataFrame:
    """Perfectly flat daily bars, for tests that need a known-quiet baseline."""
    day = pd.Timestamp('2026-01-05')
    timestamps = []
    for _ in range(n):
        while day.weekday() >= 5:
            day += timedelta(days=1)
        timestamps.append(day)
        day += timedelta(days=1)
    return pd.DataFrame({
        'timestamp': timestamps,
        'open': [price] * n,
        'high': [price] * n,
        'low': [price] * n,
        'close': [price] * n,
        'volume': [1000.0] * n,
    })


@pytest.fixture
def intraday_bars() -> pd.DataFrame:
    return make_intraday_bars()


@pytest.fixture
def daily_bars() -> pd.DataFrame:
    return make_daily_bars()


@pytest.fixture
def flat_bars() -> pd.DataFrame:
    return make_flat_bars()


# -- database fixtures -----------------------------------------------------

@pytest.fixture
def sqlite_engine(tmp_path):
    """A file-backed SQLite database with the schema created from the models.

    A file rather than :memory: so a test can dispose the engine, reconnect, and
    prove that data survived -- which is the whole point of persistence and
    cannot be shown with an in-memory database that dies with its connection.
    """
    from db.session import create_all, get_engine

    engine = get_engine(f'sqlite+pysqlite:///{tmp_path}/test.db')
    create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(sqlite_engine):
    """A session against the SQLite fixture database.

    Deliberately not `session_scope`: many of these tests assert that a
    constraint rejects a write, and `pytest.raises` swallowing the IntegrityError
    means the block exits normally. `session_scope` would then try to commit an
    already-failed transaction and every such test would error in teardown while
    reporting a pass. This fixture rolls back instead, so a constraint test is
    just a constraint test.
    """
    from sqlalchemy.orm import sessionmaker

    factory = sessionmaker(bind=sqlite_engine, expire_on_commit=False)
    session = factory()
    try:
        yield session
    finally:
        session.rollback()
        session.close()
