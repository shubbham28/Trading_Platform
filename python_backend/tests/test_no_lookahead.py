"""
Look-ahead regression tests.

A causal strategy has a testable property: everything it computes or decides at
bar i is identical whether or not bars after i exist. If truncating the data
changes an indicator value or a signal at a bar the truncation did not remove,
the strategy is reading the future, and its backtest describes an algorithm that
cannot be run live.

This is the test the previous implementation failed. Five of the eight
strategies decided "are we near the close?" with `index >= len(df) - 3`, which
is a reading of the dataset's length, so their exits moved whenever the frame
was resized -- and live, where the frame always ends at the current bar, fired
on every single bar.
"""
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal, assert_series_equal

from app.backtest import BacktestConfig, BacktestEngine
from indicators import calculate_all_indicators
from strategies import STRATEGIES, get_strategy
from tests._causality import (
    decision_backtest, decision_live, synthetic_position,
)
from tests.conftest import make_daily_bars, make_intraday_bars

STRATEGY_IDS = sorted(STRATEGIES.keys())
# Bars removed by truncation. Large enough that a strategy peeking a few bars
# ahead cannot coincidentally agree.
TRUNCATE = 40


def _indicator_columns(df: pd.DataFrame) -> list:
    return [c for c in df.columns if c not in ('timestamp',)]


@pytest.mark.parametrize('strategy_id', STRATEGY_IDS)
@pytest.mark.parametrize('timeframe', ['5Min', '1Day'])
def test_prepare_is_causal(strategy_id, timeframe):
    """Indicator values must not change when later bars are removed."""
    df = make_intraday_bars() if timeframe == '5Min' else make_daily_bars()
    strategy = get_strategy(strategy_id)

    full = strategy.prepare(calculate_all_indicators(df))
    n = len(df) - TRUNCATE
    truncated = strategy.prepare(calculate_all_indicators(df.iloc[:n].copy()))

    assert len(truncated) == n
    for col in _indicator_columns(truncated):
        assert_series_equal(
            full[col].iloc[:n].reset_index(drop=True),
            truncated[col].reset_index(drop=True),
            check_names=False,
            obj=f'{strategy_id}.{col} changed when future bars were removed',
        )


@pytest.mark.parametrize('strategy_id', STRATEGY_IDS)
@pytest.mark.parametrize('timeframe', ['5Min', '1Day'])
def test_signals_are_causal(strategy_id, timeframe):
    """Signals must not change when later bars are removed.

    Runs the full engine both times rather than calling `analyze` directly, so
    the position sequence, the fill timing and the calendar context are all part
    of what is being compared. A prefix of the longer run must equal the shorter
    run exactly.
    """
    df = make_intraday_bars() if timeframe == '5Min' else make_daily_bars()
    n = len(df) - TRUNCATE

    def run(frame: pd.DataFrame):
        return BacktestEngine(
            BacktestConfig(
                symbol='TEST', start_date='2026-01-01', end_date='2026-12-31',
                strategy_id=strategy_id, timeframe=timeframe,
            ),
            get_strategy(strategy_id),
        ).run(frame)

    full = run(df)
    truncated = run(df.iloc[:n].copy())

    # The equity curve is marked once per bar, so the first n points of the
    # longer run describe exactly the bars the shorter run saw.
    full_curve = pd.DataFrame(full.equity_curve).iloc[:n].reset_index(drop=True)
    trunc_curve = pd.DataFrame(truncated.equity_curve).reset_index(drop=True)
    assert_frame_equal(
        full_curve, trunc_curve,
        obj=f'{strategy_id} equity curve diverged on truncation',
    )

    # Trades that both runs could have seen must match. The shorter run force-
    # closes anything still open at its final bar, which the longer run does not,
    # so that one trade is legitimately different and is excluded.
    trunc_trades = [t for t in truncated.trades if not t['forced_liquidation']]
    full_trades = full.trades[:len(trunc_trades)]
    assert len(full_trades) == len(trunc_trades), (
        f'{strategy_id}: truncated run produced {len(trunc_trades)} settled '
        f'trades, full run produced {len(full_trades)} over the same bars'
    )
    for a, b in zip(full_trades, trunc_trades):
        for field in ('entry_time', 'entry_price', 'exit_time', 'exit_price',
                      'quantity', 'side', 'reason'):
            assert a[field] == b[field], (
                f'{strategy_id}: trade field {field!r} changed on truncation: '
                f'{a[field]!r} vs {b[field]!r}'
            )


@pytest.mark.parametrize('strategy_id', STRATEGY_IDS)
def test_strategy_holds_no_position_state(strategy_id):
    """A strategy must not carry position state between bars.

    The engine owns the position. When both sides kept a copy, a declined order
    left the strategy believing it was long for the rest of the run. Enforced
    structurally: attribute names that mean "I am holding something".
    """
    strategy = get_strategy(strategy_id)
    forbidden = {'position_open', 'entry_price', 'highest_price',
                 'opening_range_high', 'opening_range_low', 'opening_range_set',
                 'sector_selected'}
    present = forbidden.intersection(vars(strategy))
    assert not present, (
        f'{strategy_id} holds position state {sorted(present)}. The engine owns '
        'the position; derive what you need from `window` and `position`.'
    )


@pytest.mark.parametrize('strategy_id', STRATEGY_IDS)
def test_no_dataset_length_dependence(strategy_id):
    """Padding the data with unreachable future bars must not change decisions.

    A direct probe for the original defect. Appending bars beyond the truncation
    point cannot affect any earlier decision unless something is consulting the
    frame's length. Distinct from the truncation test: this one grows the input
    rather than shrinking it, which catches a strategy that indexes from the end.
    """
    df = make_intraday_bars(n_sessions=4)
    padded = make_intraday_bars(n_sessions=6)
    # The generator is seeded and session-by-session, so the shorter frame is a
    # true prefix of the longer one. Assert that rather than assume it.
    assert_frame_equal(padded.iloc[:len(df)].reset_index(drop=True), df)

    def signals(frame: pd.DataFrame):
        result = BacktestEngine(
            BacktestConfig(
                symbol='TEST', start_date='2026-01-01', end_date='2026-12-31',
                strategy_id=strategy_id, timeframe='5Min',
            ),
            get_strategy(strategy_id),
        ).run(frame)
        return pd.DataFrame(result.equity_curve).iloc[:len(df)]

    short_curve = signals(df).reset_index(drop=True)
    long_curve = signals(padded).reset_index(drop=True)

    # The shorter run force-liquidates at its last bar; the longer one keeps
    # holding. Compare only up to the bar before that forced exit.
    compare_to = len(df) - 1
    assert_frame_equal(
        short_curve.iloc[:compare_to], long_curve.iloc[:compare_to],
        obj=f'{strategy_id} decisions depend on how much data follows',
    )


@pytest.mark.parametrize('strategy_id', STRATEGY_IDS)
@pytest.mark.parametrize('timeframe', ['5Min', '1Day'])
@pytest.mark.parametrize('flat', [True, False], ids=['flat', 'holding'])
def test_decision_at_bar_matches_live_view(strategy_id, timeframe, flat):
    """The decision at bar i must not change when later bars exist.

    The sharpest form of the causality question, and the one the equity-curve
    prefix comparison above is too blunt to ask. Compares the backtest's decision
    at bar i against the decision the same strategy makes when the tape simply
    ends at bar i -- which is the live case. Any k-bar peek fails here.

    Run both flat and holding, because the original defect was in the exit half:
    a strategy that only ever sees `position=None` never reaches its
    flatten-by-close branch.
    """
    df = make_intraday_bars() if timeframe == '5Min' else make_daily_bars()
    strategy = get_strategy(strategy_id)
    warmup = strategy.warmup_bars()

    # Sample across the series rather than every bar: `decision_live` re-prepares
    # the frame per call, so an exhaustive sweep is quadratic for no extra signal.
    probes = [i for i in range(warmup + 5, len(df), 37)]
    assert probes, f'{strategy_id}: no probe bars after warmup of {warmup}'

    for i in probes:
        position = None if flat else synthetic_position(df, i)
        live = decision_live(strategy, df, i, timeframe, position)
        backtest = decision_backtest(strategy, df, i, timeframe, position)
        assert live.action == backtest.action, (
            f'{strategy_id} @ bar {i} ({timeframe}, '
            f'{"flat" if flat else "holding"}): decides {backtest.action!r} with '
            f'the full series in view but {live.action!r} when the data ends at '
            f'this bar. Backtest and live are different algorithms.\n'
            f'  backtest reason: {backtest.reason}\n'
            f'  live reason:     {live.reason}'
        )
        assert live.reason == backtest.reason, (
            f'{strategy_id} @ bar {i} ({timeframe}): same action, different '
            f'rationale. backtest={backtest.reason!r} live={live.reason!r}'
        )
