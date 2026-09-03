"""
Strategy behaviour tests.

Causality is necessary but not sufficient: a strategy can be perfectly causal
and still not do what its name says. Several of these did not. These tests pin
the documented behaviour to hand-built bars where the right answer is known by
construction.
"""
from datetime import timedelta

import pandas as pd
import pytest

from app.session import build_contexts
from indicators import calculate_all_indicators
from strategies import STRATEGIES, get_strategy
from strategies.base import Position
from tests.conftest import make_daily_bars, make_intraday_bars

STRATEGY_IDS = sorted(STRATEGIES.keys())
INTRADAY_IDS = [
    'morning_momentum', 'opening_range_breakout', 'vwap_reversion',
    'mean_reversion_intraday', 'sector_momentum',
]


def bars(rows, start='2026-03-02 09:30', bar_minutes=5) -> pd.DataFrame:
    """Build a frame from (open, high, low, close, volume) tuples."""
    ts0 = pd.Timestamp(start)
    return pd.DataFrame([
        {
            'timestamp': ts0 + timedelta(minutes=bar_minutes * i),
            'open': o, 'high': h, 'low': l, 'close': c, 'volume': v,
        }
        for i, (o, h, l, c, v) in enumerate(rows)
    ])


def session_bars(session_specs, bar_minutes=5, start_date='2026-03-02'):
    """Build several sessions, each from its own list of bar tuples."""
    frames, day = [], pd.Timestamp(start_date)
    for spec in session_specs:
        while day.weekday() >= 5:
            day += timedelta(days=1)
        frames.append(bars(
            spec, start=f'{day.date()} 09:30', bar_minutes=bar_minutes
        ))
        day += timedelta(days=1)
    return pd.concat(frames, ignore_index=True)


def run_at(strategy, df, i, timeframe='5Min', position=None):
    """Ask `strategy` for its decision at bar i."""
    prepared = strategy.prepare(calculate_all_indicators(df))
    contexts = build_contexts(prepared, timeframe)
    return strategy.analyze(prepared.iloc[:i + 1], contexts[i], position)


# -- contract shared by every strategy -------------------------------------

@pytest.mark.parametrize('strategy_id', STRATEGY_IDS)
def test_actions_are_always_in_the_vocabulary(strategy_id):
    """The engine only interprets buy, sell and hold."""
    df = make_intraday_bars(n_sessions=3)
    strategy = get_strategy(strategy_id)
    prepared = strategy.prepare(calculate_all_indicators(df))
    contexts = build_contexts(prepared, '5Min')

    for i in range(strategy.warmup_bars(), len(df)):
        for position in (None, Position(
            qty=5, entry_price=float(df.iloc[max(0, i - 10)]['close']),
            entry_time=df.iloc[max(0, i - 10)]['timestamp'],
        )):
            signal = strategy.analyze(prepared.iloc[:i + 1], contexts[i], position)
            assert signal.action in ('buy', 'sell', 'hold'), signal.action
            assert 0.0 <= signal.confidence <= 1.0, signal.confidence
            assert signal.reason, 'every decision must carry a reason'


@pytest.mark.parametrize('strategy_id', STRATEGY_IDS)
def test_warmup_covers_indicator_nans(strategy_id):
    """After warmup, a strategy must not be reading NaN indicator values."""
    df = make_intraday_bars(n_sessions=4)
    strategy = get_strategy(strategy_id)
    prepared = strategy.prepare(calculate_all_indicators(df))

    own_columns = [c for c in prepared.columns if c.startswith('_')]
    if not own_columns:
        pytest.skip(f'{strategy_id} declares no indicator columns')

    after_warmup = prepared[own_columns].iloc[strategy.warmup_bars():]
    nan_columns = after_warmup.columns[after_warmup.isna().any()].tolist()
    assert not nan_columns, (
        f'{strategy_id}: {nan_columns} still contain NaN after '
        f'warmup_bars()={strategy.warmup_bars()}'
    )


@pytest.mark.parametrize('strategy_id', INTRADAY_IDS)
def test_intraday_strategies_flatten_at_the_session_close(strategy_id):
    """Every intraday strategy must exit on the session's last bar.

    This is the behaviour the `len(df)` defect was standing in for. Live, that
    expression fired on every bar; now it fires once, on the real last bar.
    """
    df = make_intraday_bars(n_sessions=3, bar_minutes=5)
    contexts = build_contexts(df, '5Min')
    last_bars = [c.index for c in contexts if c.is_session_last_bar]
    assert last_bars, 'fixture has no session-closing bars'

    strategy = get_strategy(strategy_id)
    for i in last_bars:
        if i < strategy.warmup_bars():
            continue
        entry_idx = max(0, i - 8)
        position = Position(
            qty=10,
            entry_price=float(df.iloc[entry_idx]['close']),
            entry_time=df.iloc[entry_idx]['timestamp'],
        )
        signal = run_at(strategy, df, i, position=position)
        assert signal.action == 'sell', (
            f'{strategy_id} held a position through the session close at bar {i}: '
            f'{signal.reason}'
        )


@pytest.mark.parametrize('strategy_id', INTRADAY_IDS)
def test_intraday_strategies_open_nothing_on_the_closing_bar(strategy_id):
    """Do not open a position the flatten rule would shut on the same bar."""
    df = make_intraday_bars(n_sessions=3, bar_minutes=5)
    contexts = build_contexts(df, '5Min')
    strategy = get_strategy(strategy_id)

    for c in contexts:
        if not c.is_session_last_bar or c.index < strategy.warmup_bars():
            continue
        signal = run_at(strategy, df, c.index, position=None)
        assert signal.action != 'buy', (
            f'{strategy_id} opened a position on the closing bar: {signal.reason}'
        )


# -- opening range breakout -------------------------------------------------

def test_opening_range_is_recomputed_each_session():
    """The range must come from this session, not from the first session.

    The old implementation set the range once, from the first `range_period` bars
    of the whole dataset, and reused it for every session after -- so on a
    three-month backtest, day one priced sixty days of breakouts.

    Session one ranges up to 120. Session two's own opening range tops out at
    104, and price then reaches 106: below session one's high, but a genuine
    breakout of session two's range.
    """
    quiet_volume, spike_volume = 1_000.0, 10_000.0
    session_one = (
        [(100, 120, 99, 119, quiet_volume)]            # wide first bar
        + [(119, 120, 118, 119, quiet_volume)] * 12
    )
    session_two = (
        [(100, 104, 99, 103, quiet_volume)] * 7        # range: high 104
        + [(103, 106, 103, 106, spike_volume)]         # breakout on volume
        + [(106, 107, 105, 106, quiet_volume)] * 5
    )
    df = session_bars([session_one, session_two])

    strategy = get_strategy('opening_range_breakout', {
        'range_minutes': 30, 'volume_period': 3, 'volume_threshold': 1.5,
    })
    breakout_bar = len(session_one) + 7

    signal = run_at(strategy, df, breakout_bar, position=None)
    assert signal.action == 'buy', (
        f'no breakout on session two\'s own range: {signal.reason}'
    )
    assert '104' in signal.reason, (
        f"breakout priced against the wrong session's range: {signal.reason}"
    )


def test_opening_range_holds_during_the_range_window():
    """No entries before the range is established."""
    session = [(100, 104, 99, 103, 1_000.0)] * 14
    df = session_bars([session])
    strategy = get_strategy('opening_range_breakout', {
        'range_minutes': 30, 'volume_period': 3,
    })

    for i in range(strategy.warmup_bars(), 6):  # first 30 minutes = 6 bars
        signal = run_at(strategy, df, i, position=None)
        assert signal.action == 'hold', signal.reason


def test_opening_range_refuses_daily_bars():
    """An opening range is not defined on daily data; say so, do not guess."""
    df = make_daily_bars(n=60)
    strategy = get_strategy('opening_range_breakout', {'volume_period': 3})
    signal = run_at(strategy, df, 40, timeframe='1Day', position=None)

    assert signal.action == 'hold'
    assert 'intraday' in signal.reason.lower()


# -- morning momentum -------------------------------------------------------

def test_gap_is_measured_against_the_previous_session_close():
    """A real overnight gap, not a bar-to-bar one.

    Session one closes at 100. Session two opens at 105, a 5% overnight gap.
    Within session two no single bar gaps at all, so a bar-to-bar measurement --
    what the old code did -- would find nothing.
    """
    quiet, spike = 1_000.0, 8_000.0
    # Session one ends with a small down bar so the RSI window contains a loss.
    # A gap bar is itself one large positive delta, so a short-period RSI reads
    # close to 100 on it; `rsi_max` is set wide here to keep this test about gap
    # measurement rather than about that interaction.
    session_one = [(100, 101, 99, 100, quiet)] * 9 + [(100, 100, 98.5, 99, quiet)]
    session_two = (
        [(105, 106, 104, 105.5, spike)]
        + [(105.5, 106, 105, 105.5, quiet)] * 9
    )
    df = session_bars([session_one, session_two])

    strategy = get_strategy('morning_momentum', {
        'gap_threshold': 2.0, 'rsi_period': 3, 'rsi_max': 95,
        'volume_period': 4, 'volume_ratio_min': 2.0, 'entry_window_minutes': 30,
    })
    signal = run_at(strategy, df, len(session_one), position=None)

    assert signal.action == 'buy', f'overnight gap not detected: {signal.reason}'
    assert 'gap up' in signal.reason


def test_morning_entry_window_is_enforced():
    """A morning strategy must not enter in the afternoon.

    The old code set `is_market_open_period = True` unconditionally, so the gap
    filter ran on every bar of the day.
    """
    quiet, spike = 1_000.0, 8_000.0
    session_one = [(100, 101, 99, 100, quiet)] * 10
    # Gap up, then a volume spike late in the session that would otherwise
    # satisfy every entry condition.
    session_two = (
        [(105, 106, 104, 105.5, quiet)] * 20
        + [(105.5, 106, 105, 105.5, spike)]
    )
    df = session_bars([session_one, session_two])

    strategy = get_strategy('morning_momentum', {
        'gap_threshold': 2.0, 'rsi_period': 3, 'volume_period': 4,
        'volume_ratio_min': 2.0, 'entry_window_minutes': 30,
    })
    late_bar = len(df) - 1
    signal = run_at(strategy, df, late_bar, position=None)

    assert signal.action == 'hold'
    assert 'entry window' in signal.reason.lower() or 'closing' in signal.reason.lower()


def test_trailing_stop_is_derived_from_bars_since_entry():
    """The high-water mark comes from the window, not from strategy state."""
    quiet = 1_000.0
    session = (
        [(100, 100.5, 99.5, 100, quiet)] * 6
        + [(100, 110, 100, 110, quiet)]      # spike to 110 after entry
        + [(110, 110, 104, 104, quiet)]      # falls through a 2% trailing stop
    )
    df = session_bars([session])
    strategy = get_strategy('morning_momentum', {
        'rsi_period': 3, 'volume_period': 4, 'trailing_stop_pct': 2.0,
    })

    position = Position(
        qty=10, entry_price=100.0, entry_time=df.iloc[5]['timestamp']
    )
    signal = run_at(strategy, df, len(session) - 1, position=position)

    assert signal.action == 'sell'
    assert 'trailing stop' in signal.reason.lower()


# -- mean reversion intraday ------------------------------------------------

def test_bollinger_confirmation_actually_gates_entry():
    """The documented filter must be a filter.

    Previously `near_lower_bb` only nudged the confidence score while the entry
    fired regardless, so the strategy took every oversold reading despite its
    docstring.
    """
    # A steady decline: RSI goes oversold while price sits above the lower band.
    session = [(100 - i * 0.05, 100 - i * 0.05 + 0.1, 100 - i * 0.05 - 0.1,
                100 - i * 0.05, 1_000.0) for i in range(40)]
    df = session_bars([session])

    gated = get_strategy('mean_reversion_intraday', {
        'rsi_period': 3, 'bb_period': 10, 'require_bb_confirmation': True,
        'bb_tolerance_pct': 0.0,
    })
    ungated = get_strategy('mean_reversion_intraday', {
        'rsi_period': 3, 'bb_period': 10, 'require_bb_confirmation': False,
        'bb_tolerance_pct': 0.0,
    })

    # Find a bar where the two disagree; that difference is the filter working.
    disagreed = False
    for i in range(15, len(session) - 1):
        a = run_at(gated, df, i, position=None)
        b = run_at(ungated, df, i, position=None)
        if a.action != b.action:
            disagreed = True
            assert b.action == 'buy' and a.action == 'hold'
            assert 'above lower band' in a.reason
            break
    assert disagreed, 'the Bollinger filter never changed an entry decision'


# -- daily strategies -------------------------------------------------------

def test_sma_crossover_fires_on_a_constructed_crossing():
    """A known bullish crossing must produce exactly one buy."""
    # Flat, then a sustained rise: the fast average crosses up through the slow.
    flat = [(100, 100.2, 99.8, 100, 1_000.0)] * 25
    rising = [(100 + i, 100 + i + 0.3, 100 + i - 0.3, 100 + i + 0.2, 1_000.0)
              for i in range(1, 16)]
    day = pd.Timestamp('2026-01-05')
    rows, prices = [], flat + rising
    for o, h, l, c, v in prices:
        while day.weekday() >= 5:
            day += timedelta(days=1)
        rows.append({'timestamp': day, 'open': o, 'high': h, 'low': l,
                     'close': c, 'volume': v})
        day += timedelta(days=1)
    df = pd.DataFrame(rows)

    strategy = get_strategy('sma_crossover', {'short_period': 3, 'long_period': 10})
    actions = [
        run_at(strategy, df, i, timeframe='1Day', position=None).action
        for i in range(strategy.warmup_bars(), len(df))
    ]
    assert actions.count('buy') == 1, f'expected one crossing, got {actions}'


def test_rsi_strategy_signals_on_a_constructed_oversold_recovery():
    decline = [(100 - i, 100 - i + 0.2, 100 - i - 0.2, 100 - i, 1_000.0)
               for i in range(20)]
    recovery = [(81 + i, 81 + i + 0.2, 81 + i - 0.2, 81 + i, 1_000.0)
                for i in range(1, 10)]
    day = pd.Timestamp('2026-01-05')
    rows = []
    for o, h, l, c, v in decline + recovery:
        while day.weekday() >= 5:
            day += timedelta(days=1)
        rows.append({'timestamp': day, 'open': o, 'high': h, 'low': l,
                     'close': c, 'volume': v})
        day += timedelta(days=1)
    df = pd.DataFrame(rows)

    strategy = get_strategy('rsi_mean_revert', {'period': 5, 'oversold': 30})
    actions = [
        run_at(strategy, df, i, timeframe='1Day', position=None).action
        for i in range(strategy.warmup_bars(), len(df))
    ]
    assert 'buy' in actions, f'no oversold recovery detected: {actions}'


# -- parameter validation ---------------------------------------------------

@pytest.mark.parametrize('strategy_id,bad_params', [
    ('sma_crossover', {'short_period': 30, 'long_period': 10}),
    ('rsi_mean_revert', {'oversold': 80, 'overbought': 20}),
    ('macd_trend_follow', {'fast_period': 30, 'slow_period': 12}),
    ('vwap_reversion', {'ema_fast': 50, 'ema_slow': 20}),
    ('opening_range_breakout', {'range_minutes': 0}),
    ('morning_momentum', {'gap_threshold': -1}),
    ('mean_reversion_intraday', {'rsi_oversold': 60, 'rsi_target': 40}),
    ('sector_momentum', {'rsi_min': 80, 'rsi_max': 50}),
])
def test_invalid_parameters_are_rejected(strategy_id, bad_params):
    with pytest.raises(ValueError):
        STRATEGIES[strategy_id].validate_parameters(bad_params)
