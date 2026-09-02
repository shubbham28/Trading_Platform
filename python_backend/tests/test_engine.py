"""
Engine tests: one per defect the rewrite fixed.

Each test names the behaviour it pins down. A regression here means backtest
numbers have stopped describing reachable trades.
"""
from datetime import timedelta

import numpy as np
import pandas as pd
import pytest

from app.backtest import (
    BacktestConfig, BacktestEngine, TRADING_DAYS_PER_YEAR, periods_per_year,
)
from strategies.base import BarContext, BaseStrategy, Position, Signal
from tests.conftest import make_daily_bars, make_intraday_bars


def _config(**overrides) -> BacktestConfig:
    base = dict(
        symbol='TEST', start_date='2026-01-01', end_date='2026-12-31',
        strategy_id='test', initial_capital=10_000.0, timeframe='1Day',
        slippage_bps=0.0,
    )
    base.update(overrides)
    return BacktestConfig(**base)


class ScriptedStrategy(BaseStrategy):
    """Emits a predetermined action per bar index, so fills are checkable."""

    def _initialize(self):
        self.script = self.parameters.get('script', {})

    def analyze(self, window, ctx, position):
        action = self.script.get(ctx.index, 'hold')
        return Signal(
            timestamp=ctx.timestamp, action=action, confidence=1.0,
            reason=f'scripted {action}', price=float(window.iloc[-1]['close']),
        )


def _ramp(n: int = 12, start: float = 100.0, step: float = 1.0) -> pd.DataFrame:
    """Daily bars whose open and close differ, so fill timing is observable.

    Each bar opens at a known price and closes higher. A fill at the signal
    bar's close and a fill at the next bar's open are therefore different
    numbers, which is what makes the timing testable at all.
    """
    day = pd.Timestamp('2026-01-05')
    rows = []
    for i in range(n):
        while day.weekday() >= 5:
            day += timedelta(days=1)
        bar_open = start + step * i
        bar_close = bar_open + step * 0.5
        rows.append({
            'timestamp': day,
            'open': bar_open,
            'high': bar_close + 0.25,
            'low': bar_open - 0.25,
            'close': bar_close,
            'volume': 1_000.0,
        })
        day += timedelta(days=1)
    return pd.DataFrame(rows)


# -- fill timing -----------------------------------------------------------

def test_fill_happens_at_next_bar_open_not_signal_bar_close():
    """Defect 3. You cannot observe a close and trade at it."""
    df = _ramp()
    engine = BacktestEngine(
        _config(), ScriptedStrategy({'script': {3: 'buy', 7: 'sell'}})
    )
    result = engine.run(df)

    assert len(result.trades) == 1
    trade = result.trades[0]

    signal_bar_close = float(df.iloc[3]['close'])
    next_bar_open = float(df.iloc[4]['open'])
    assert next_bar_open != signal_bar_close, 'fixture cannot distinguish the two'

    assert trade['entry_price'] == pytest.approx(next_bar_open), (
        'entry filled at the signal bar close instead of the next bar open'
    )
    assert trade['entry_time'] == df.iloc[4]['timestamp']
    assert trade['exit_price'] == pytest.approx(float(df.iloc[8]['open']))
    assert trade['exit_time'] == df.iloc[8]['timestamp']


def test_final_bar_intent_is_counted_not_filled():
    """An intent on the last bar has no bar to fill against."""
    df = _ramp()
    last = len(df) - 1
    result = BacktestEngine(
        _config(), ScriptedStrategy({'script': {last: 'buy'}})
    ).run(df)

    assert result.audit.intents_unfilled_no_next_bar == 1
    assert result.trades == []
    assert result.final_capital == pytest.approx(10_000.0)


def test_slippage_is_charged_against_the_trade_in_both_directions():
    """Buys pay up, sells receive less, on entry and on exit."""
    df = _ramp()
    script = {'script': {2: 'buy', 6: 'sell'}}

    clean = BacktestEngine(_config(slippage_bps=0.0), ScriptedStrategy(script)).run(df)
    slipped = BacktestEngine(_config(slippage_bps=50.0), ScriptedStrategy(script)).run(df)

    assert slipped.trades[0]['entry_price'] > clean.trades[0]['entry_price']
    assert slipped.trades[0]['exit_price'] < clean.trades[0]['exit_price']
    assert slipped.trades[0]['pnl'] < clean.trades[0]['pnl']


def test_slippage_defaults_to_nonzero():
    """Zero-cost trading is a false assumption, not a conservative one."""
    assert BacktestConfig(
        symbol='X', start_date='a', end_date='b', strategy_id='s'
    ).slippage_bps > 0


# -- position sizing -------------------------------------------------------

def test_position_size_respects_max_position_pct():
    """Defect 5. All-in was hardcoded; now it is a visible knob."""
    df = _ramp()
    script = {'script': {2: 'buy'}}

    full = BacktestEngine(
        _config(max_position_pct=100.0), ScriptedStrategy(script)
    ).run(df)
    quarter = BacktestEngine(
        _config(max_position_pct=25.0), ScriptedStrategy(script)
    ).run(df)

    full_qty = full.trades[0]['quantity']
    quarter_qty = quarter.trades[0]['quantity']
    assert quarter_qty * 4 == pytest.approx(full_qty, abs=4)
    assert quarter_qty < full_qty


def test_insufficient_capital_is_recorded_not_swallowed():
    """Defect 4's root cause: a declined order used to vanish silently."""
    df = _ramp(start=10_000.0, step=100.0)
    result = BacktestEngine(
        _config(initial_capital=50.0), ScriptedStrategy({'script': {2: 'buy'}})
    ).run(df)

    assert result.trades == []
    assert result.audit.intents_rejected_insufficient_capital == 1


def test_strategy_cannot_desync_from_engine_position():
    """Defect 4. The engine's position is the only copy.

    After a declined buy the strategy must still be told it is flat, so a later
    buy is still considered. The old code left the strategy believing it held a
    position for the rest of the run.
    """
    seen = []

    class Recorder(BaseStrategy):
        def analyze(self, window, ctx, position):
            seen.append((ctx.index, position.qty if position else 0))
            # Priced out at bar 2, affordable once capital allows at bar 5.
            action = 'buy' if ctx.index in (2, 6) else 'hold'
            return Signal(
                timestamp=ctx.timestamp, action=action, confidence=1.0,
                reason='recorder', price=float(window.iloc[-1]['close']),
            )

    # Explicit prices rather than the ramp: the decline has to be caused by the
    # share price exceeding the account, and a later bar has to be affordable.
    day = pd.Timestamp('2026-01-05')
    rows = []
    for i, price in enumerate([500.0] * 6 + [100.0] * 4):
        while day.weekday() >= 5:
            day += timedelta(days=1)
        rows.append({
            'timestamp': day, 'open': price, 'high': price + 1,
            'low': price - 1, 'close': price, 'volume': 1_000.0,
        })
        day += timedelta(days=1)
    df = pd.DataFrame(rows)

    result = BacktestEngine(_config(initial_capital=150.0), Recorder()).run(df)

    positions_after_decline = [qty for idx, qty in seen if idx in (3, 4)]
    assert positions_after_decline == [0, 0], (
        'strategy was told it held a position after the order was declined'
    )
    assert result.trades, 'the later affordable buy never happened'


# -- shorts ----------------------------------------------------------------

def test_short_is_rejected_and_counted_when_shorts_disabled():
    """Defect 6. A short used to be silently impossible."""
    df = _ramp()
    result = BacktestEngine(
        _config(allow_short=False), ScriptedStrategy({'script': {2: 'sell'}})
    ).run(df)

    assert result.trades == []
    assert result.audit.intents_rejected_shorts_disabled == 1


def test_short_round_trip_profits_when_price_falls():
    """A short is reachable, marks correctly, and profits on a decline."""
    df = _ramp(n=12, start=200.0, step=-5.0)  # falling market
    result = BacktestEngine(
        _config(allow_short=True), ScriptedStrategy({'script': {2: 'sell', 8: 'buy'}})
    ).run(df)

    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade['side'] == 'short'
    assert trade['exit_price'] < trade['entry_price']
    assert trade['pnl'] > 0
    assert trade['pnl_pct'] > 0, 'short pnl_pct has the wrong sign'
    assert result.final_capital > result.initial_capital


def test_short_loses_when_price_rises():
    """The sign convention holds in the losing direction too."""
    df = _ramp(n=12, start=100.0, step=5.0)  # rising market
    result = BacktestEngine(
        _config(allow_short=True), ScriptedStrategy({'script': {2: 'sell', 8: 'buy'}})
    ).run(df)

    trade = result.trades[0]
    assert trade['side'] == 'short'
    assert trade['pnl'] < 0
    assert trade['pnl_pct'] < 0
    assert result.final_capital < result.initial_capital


# -- accounting ------------------------------------------------------------

def test_forced_liquidation_is_flagged_and_counted():
    """A position closed by the end of data is not a strategy exit."""
    df = _ramp()
    result = BacktestEngine(
        _config(), ScriptedStrategy({'script': {2: 'buy'}})
    ).run(df)

    assert len(result.trades) == 1
    assert result.trades[0]['forced_liquidation'] is True
    assert result.audit.forced_liquidations == 1


def test_final_capital_is_realised_cash_not_a_units_mismatch():
    """Defect 15. The old expression multiplied share count by dollar equity."""
    df = _ramp()
    result = BacktestEngine(
        _config(), ScriptedStrategy({'script': {2: 'buy', 6: 'sell'}})
    ).run(df)

    entry, exit_ = result.trades[0]['entry_price'], result.trades[0]['exit_price']
    qty = result.trades[0]['quantity']
    expected = 10_000.0 + (exit_ - entry) * qty
    assert result.final_capital == pytest.approx(expected)
    assert result.total_return == pytest.approx(expected - 10_000.0)


def test_profit_factor_is_none_when_nothing_lost():
    """The old code divided by 1.0, producing a fake ratio."""
    df = _ramp()  # monotonically rising, so the long cannot lose
    result = BacktestEngine(
        _config(), ScriptedStrategy({'script': {2: 'buy', 6: 'sell'}})
    ).run(df)

    assert result.losing_trades == 0
    assert result.profit_factor is None


def test_commission_is_charged_on_both_legs():
    df = _ramp()
    script = {'script': {2: 'buy', 6: 'sell'}}
    free = BacktestEngine(_config(commission=0.0), ScriptedStrategy(script)).run(df)
    paid = BacktestEngine(_config(commission=0.01), ScriptedStrategy(script)).run(df)

    assert paid.trades[0]['commission'] > 0
    assert paid.trades[0]['pnl'] < free.trades[0]['pnl']
    assert paid.final_capital < free.final_capital


def test_result_carries_its_cost_assumptions():
    """A number must never be quotable without the costs that produced it."""
    result = BacktestEngine(
        _config(commission=0.002, slippage_bps=3.0, max_position_pct=40.0,
                allow_short=True, timeframe='1Day'),
        ScriptedStrategy({'script': {}}),
    ).run(_ramp())

    assert result.commission == 0.002
    assert result.slippage_bps == 3.0
    assert result.max_position_pct == 40.0
    assert result.allow_short is True
    assert result.timeframe == '1Day'


# -- annualisation ---------------------------------------------------------

def test_periods_per_year_tracks_bar_size():
    """Defect 16. sqrt(252) on minute bars overstates Sharpe ~20x."""
    assert periods_per_year('1Day') == TRADING_DAYS_PER_YEAR
    assert periods_per_year('1Min') == pytest.approx(390 * 252)
    assert periods_per_year('5Min') == pytest.approx(78 * 252)
    assert periods_per_year('1Hour') == pytest.approx((390 / 60) * 252)
    assert periods_per_year('1Week') == 52
    assert periods_per_year('1Month') == 12


def test_sharpe_scales_with_declared_timeframe():
    """The same bars annualised as 5Min must not match annualised as 1Day."""
    df = make_intraday_bars(n_sessions=4)
    script = {'script': {i: ('buy' if i % 20 == 0 else 'sell') for i in range(0, 300, 10)}}

    as_intraday = BacktestEngine(
        _config(timeframe='5Min'), ScriptedStrategy(script)
    ).run(df)
    as_daily = BacktestEngine(
        _config(timeframe='1Day'), ScriptedStrategy(script)
    ).run(df)

    if as_daily.sharpe_ratio == 0:
        pytest.skip('fixture produced no return variance to annualise')

    ratio = abs(as_intraday.sharpe_ratio / as_daily.sharpe_ratio)
    expected = np.sqrt(periods_per_year('5Min') / periods_per_year('1Day'))
    assert ratio == pytest.approx(expected, rel=1e-6)
    assert ratio > 8, 'intraday Sharpe is not being scaled by bar size at all'


def test_empty_data_is_rejected():
    with pytest.raises(ValueError, match='No data'):
        BacktestEngine(_config(), ScriptedStrategy({})).run(pd.DataFrame())


def test_missing_timestamp_column_is_rejected():
    df = _ramp().drop(columns=['timestamp'])
    with pytest.raises(ValueError, match='timestamp'):
        BacktestEngine(_config(), ScriptedStrategy({})).run(df)
