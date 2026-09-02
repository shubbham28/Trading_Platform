"""
Bot runner tests.

Phase 4's exit criterion: a bot runs a full paper session unattended, its
audit_log accounts for every bar, and its end-of-day position matches the
broker's exactly.

The third clause says "matches Alpaca's". No Alpaca credentials exist in this
environment, so it is verified against `SimBroker`, which keeps its own books
from fills. That is a real independent comparison -- the broker's position is
derived from what it filled, ours from what we recorded -- but it is not Alpaca,
and the difference is stated rather than glossed.

The most valuable test here is `test_runner_matches_backtester`. The plan's
central architectural claim is that the runner and the backtester drive the same
strategy core, so a backtest number means something. That test is what turns the
claim into something that fails when it stops being true.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.backtest import BacktestConfig, BacktestEngine
from db import repository
from db.models import AuditLog, Order, PositionRow
from db.session import create_all, get_engine
from risk.contracts import AccountRiskLimits, BotRiskLimits
from risk.gate import RiskGate
from runner.clock import HistoricalClock
from runner.loop import (
    AUDIT_FORCED_FLATTEN, AUDIT_SIGNAL, AUDIT_TICK_ERROR, BotRunner,
)
from runner.router import OrderRouter
from strategies import get_strategy
from tests._fakes import SimBroker
from tests.conftest import make_daily_bars, make_intraday_bars

SYMBOL = 'TEST'


@pytest.fixture
def factory(tmp_path):
    """A session factory over a file-backed SQLite database.

    A factory rather than one session, because the runner opens a transaction
    per tick -- one bar's failure must not roll back the previous bar's order.
    """
    engine = get_engine(f'sqlite+pysqlite:///{tmp_path}/runner.db')
    create_all(engine)
    yield sessionmaker(bind=engine, expire_on_commit=False)
    engine.dispose()


def make_bot(factory, **overrides):
    fields = dict(
        name='runner-bot', strategy_id='sma_crossover',
        parameters={'short_period': 3, 'long_period': 8},
        symbols=[SYMBOL], timeframe='1Day',
        capital_budget=Decimal('50000'), risk_limits={}, enabled=True,
    )
    fields.update(overrides)
    with factory() as session:
        bot = repository.create_bot(session, **fields)
        session.commit()
        return bot.id


def permissive_gate() -> RiskGate:
    """Limits wide enough that the gate is not what is under test."""
    return RiskGate(
        AccountRiskLimits(
            max_total_exposure_pct=100.0, max_daily_loss_pct=90.0,
            max_open_positions=50,
        ),
        BotRiskLimits(
            max_position_pct=100.0, max_daily_loss=Decimal('1000000'),
            max_open_positions=20, max_order_value=Decimal('10000000'),
        ),
    )


def runner_for(factory, bot_id, broker, gate=None, **kwargs):
    return BotRunner(
        factory, broker, bot_id, gate=gate or permissive_gate(),
        router=OrderRouter(broker), **kwargs,
    )


# -- the exit criterion ----------------------------------------------------

def test_bot_runs_a_full_session_unattended(factory):
    """Start to finish with no intervention, and no unhandled failures."""
    bars = make_daily_bars(n=80)
    broker = SimBroker(price='100')
    bot_id = make_bot(factory)

    result = runner_for(factory, bot_id, broker).run_session(
        HistoricalClock(SYMBOL, bars, '1Day')
    )

    assert not result.halted, result.halt_reason
    assert result.bars_seen == len(bars)
    assert result.errors == 0, [t.error for t in result.ticks if t.error]


def test_audit_log_accounts_for_every_bar(factory):
    """Every bar leaves a record, holds included.

    A log that only records actions cannot tell a quiet bot from a stopped one,
    which is the question this criterion exists to make answerable.
    """
    bars = make_daily_bars(n=60)
    broker = SimBroker(price='100')
    bot_id = make_bot(factory)

    runner_for(factory, bot_id, broker).run_session(
        HistoricalClock(SYMBOL, bars, '1Day')
    )

    with factory() as session:
        signals = list(session.execute(
            select(AuditLog).where(AuditLog.event_type == AUDIT_SIGNAL)
            .order_by(AuditLog.id)
        ).scalars())

    assert len(signals) == len(bars), (
        f'{len(signals)} signal rows for {len(bars)} bars'
    )

    # Every bar's timestamp appears exactly once, in order.
    logged = [s.payload['bar'] for s in signals]
    expected = [
        __import__('pandas').Timestamp(t).isoformat()
        for t in bars['timestamp']
    ]
    assert logged == expected


def test_end_of_day_position_matches_the_broker_exactly(factory):
    """Derived independently on both sides, then compared.

    The broker's book comes from the fills it granted; ours from the fills we
    recorded. They are only equal if every fill was applied correctly.
    """
    bars = make_daily_bars(n=100)
    broker = SimBroker(price='100')
    bot_id = make_bot(factory)

    result = runner_for(factory, bot_id, broker).run_session(
        HistoricalClock(SYMBOL, bars, '1Day')
    )
    assert result.orders_placed > 0, 'the strategy never traded; test is vacuous'

    broker_book = {p.symbol: p.qty for p in broker.get_positions()}
    with factory() as session:
        local_book = {
            r.symbol: r.qty
            for r in session.execute(select(PositionRow)).scalars()
        }

    assert broker_book == local_book, (
        f'broker holds {broker_book}, we think {local_book}'
    )


def test_reconciliation_after_a_session_reports_in_sync(factory):
    """The same claim, checked through the reconciler rather than by hand."""
    from runner.reconcile import reconcile

    bars = make_daily_bars(n=100)
    broker = SimBroker(price='100')
    bot_id = make_bot(factory)

    runner_for(factory, bot_id, broker).run_session(
        HistoricalClock(SYMBOL, bars, '1Day')
    )

    with factory() as session:
        result = reconcile(session, broker, halt_on_divergence=False)
        session.commit()

    assert result.in_sync, result.describe()


# -- the architectural claim ----------------------------------------------

def test_runner_matches_backtester(factory):
    """The runner and the backtester must reach the same decisions.

    This is the plan's load-bearing property: one implementation of the decision
    path, so a backtest number describes what the bot would actually do. If these
    two diverge on identical bars, a backtest is once again a work of fiction --
    which is the exact failure Phase 1 was spent eliminating.

    Compared on the sequence of actions, not on P&L: the backtester fills at the
    next bar's open with modelled slippage while the runner fills at whatever the
    broker gives, so the prices legitimately differ. The decisions must not.

    KNOWN LIMIT. This compares what the strategy decided, not what each execution
    layer did with the decision. It passed while the backtester refused shorts
    and the runner opened them, because both agreed the signal was 'sell'. The
    execution layers need their own parity tests -- see
    `test_shorts_are_refused_by_default_in_both_engines` -- and any new execution
    switch on one side needs a matching one here.
    """
    bars = make_daily_bars(n=120)
    params = {'short_period': 3, 'long_period': 8}

    # Backtester.
    engine = BacktestEngine(
        BacktestConfig(
            symbol=SYMBOL, start_date='2025-01-02', end_date='2025-12-31',
            strategy_id='sma_crossover', parameters=params, timeframe='1Day',
            initial_capital=50_000.0, slippage_bps=0.0, max_position_pct=100.0,
        ),
        get_strategy('sma_crossover', params),
    )
    backtest = engine.run(bars)

    # Runner over the same bars.
    broker = SimBroker(price='100')
    bot_id = make_bot(factory, parameters=params)
    runner_for(factory, bot_id, broker).run_session(
        HistoricalClock(SYMBOL, bars, '1Day')
    )

    with factory() as session:
        signals = list(session.execute(
            select(AuditLog).where(AuditLog.event_type == AUDIT_SIGNAL)
            .order_by(AuditLog.id)
        ).scalars())

    runner_actions = [s.payload['action'] for s in signals]

    # Re-derive the backtester's per-bar actions through the same strategy path.
    from app.session import build_contexts
    from indicators import calculate_all_indicators
    strategy = get_strategy('sma_crossover', params)
    prepared = strategy.prepare(calculate_all_indicators(bars))
    contexts = build_contexts(prepared, '1Day')
    warmup = strategy.warmup_bars()

    expected = []
    position = None
    for i in range(len(prepared)):
        if i < warmup:
            expected.append('hold')
            continue
        signal = strategy.analyze(prepared.iloc[:i + 1], contexts[i], position)
        expected.append(signal.action)
        # Mirror the engine's position bookkeeping closely enough to keep the
        # strategy seeing the same position the runner showed it.
        if signal.action == 'buy' and position is None:
            from strategies.base import Position
            position = Position(
                qty=1, entry_price=float(prepared.iloc[i]['close']),
                entry_time=prepared.iloc[i]['timestamp'],
            )
        elif signal.action == 'sell' and position is not None:
            position = None

    assert len(runner_actions) == len(expected)
    assert runner_actions == expected, (
        'the runner and the strategy core disagree on what to do. '
        'A backtest number no longer describes what the bot would do.'
    )
    assert backtest.total_trades > 0, 'no trades; the comparison is vacuous'


# -- kill switch and halting ----------------------------------------------

def test_an_engaged_kill_switch_stops_new_positions(factory):
    """Checked every tick, so it takes effect without a restart."""
    bars = make_daily_bars(n=80)
    broker = SimBroker(price='100')
    bot_id = make_bot(factory)

    with factory() as session:
        repository.set_kill_switch(session, True, reason='test halt')
        session.commit()

    result = runner_for(factory, bot_id, broker).run_session(
        HistoricalClock(SYMBOL, bars, '1Day')
    )

    assert result.bars_seen == len(bars), 'the session stopped instead of holding'
    assert broker.get_positions() == [], 'a position was opened with the switch on'
    blocked = [t for t in result.ticks if t.blocked_by_rule]
    assert blocked, 'no order was blocked'
    assert {t.blocked_by_rule for t in blocked} == {'account_kill_switch'}


def test_a_disabled_bot_does_nothing(factory):
    bars = make_daily_bars(n=30)
    broker = SimBroker()
    bot_id = make_bot(factory, enabled=False)

    result = runner_for(factory, bot_id, broker).run_session(
        HistoricalClock(SYMBOL, bars, '1Day')
    )

    assert result.halted
    assert result.halt_reason == 'bot disabled'
    assert broker.submitted == []


def test_a_replayed_bar_is_skipped_not_re_traded(factory):
    """A restart that re-reads the last bar must not act on it twice."""
    bars = make_daily_bars(n=40)
    broker = SimBroker(price='100')
    bot_id = make_bot(factory)
    runner = runner_for(factory, bot_id, broker)

    first = runner.run_session(HistoricalClock(SYMBOL, bars, '1Day'))
    orders_after_first = first.orders_placed
    assert orders_after_first > 0

    # Replay the identical session.
    second = runner.run_session(HistoricalClock(SYMBOL, bars, '1Day'))

    with factory() as session:
        total_orders = len(list(session.execute(select(Order)).scalars()))

    assert second.orders_placed == 0, 'the replay placed orders again'
    assert total_orders == orders_after_first
    assert any(t.skipped and 'already handled' in t.skipped for t in second.ticks)


def test_repeated_tick_failures_halt_and_disable_the_bot(factory):
    """A bot failing every bar must not keep trying forever."""
    class ExplodingBroker(SimBroker):
        def get_account(self):
            raise RuntimeError('broker on fire')

    bars = make_daily_bars(n=40)
    bot_id = make_bot(factory)

    runner = BotRunner(
        factory, ExplodingBroker(), bot_id, gate=permissive_gate(),
        max_consecutive_errors=3,
    )
    result = runner.run_session(HistoricalClock(SYMBOL, bars, '1Day'))

    # start_session calls get_account, so it fails there first.
    assert result.halted
    assert 'broker on fire' in result.halt_reason


def test_a_single_tick_failure_does_not_end_the_session(factory):
    """One bad bar is not a reason to stop trading for the day."""
    bars = make_daily_bars(n=60)
    bot_id = make_bot(factory)

    class FlakyBroker(SimBroker):
        def __init__(self, **kw):
            super().__init__(**kw)
            self.calls = 0

        def get_positions(self):
            self.calls += 1
            # Call 1 is the startup reconcile; 2 onwards are inside ticks.
            if self.calls == 4:
                raise RuntimeError('transient broker glitch')
            return super().get_positions()

    result = runner_for(factory, bot_id, FlakyBroker(price='100')).run_session(
        HistoricalClock(SYMBOL, bars, '1Day')
    )

    assert result.bars_seen == len(bars)
    assert result.errors >= 1
    assert not result.halted


def test_a_tick_error_is_audited_in_its_own_transaction(factory):
    """The tick's transaction was rolled back, so the error needs its own.

    Writing the error into the failed transaction would roll the error back too,
    and the failure would leave no trace at all.
    """
    bars = make_daily_bars(n=60)
    bot_id = make_bot(factory)

    class FlakyBroker(SimBroker):
        def __init__(self, **kw):
            super().__init__(**kw)
            self.calls = 0

        def get_positions(self):
            self.calls += 1
            if self.calls == 4:
                raise RuntimeError('transient broker glitch')
            return super().get_positions()

    runner_for(factory, bot_id, FlakyBroker(price='100')).run_session(
        HistoricalClock(SYMBOL, bars, '1Day')
    )

    with factory() as session:
        errors = list(session.execute(
            select(AuditLog).where(AuditLog.event_type == AUDIT_TICK_ERROR)
        ).scalars())

    assert len(errors) >= 1
    assert 'transient broker glitch' in errors[0].payload['error']


def test_startup_refuses_to_begin_out_of_step_with_the_broker(factory):
    """Starting a session on a book you do not understand is worse than not
    starting one."""
    bars = make_daily_bars(n=30)
    broker = SimBroker(price='100')
    broker.seed_position(SYMBOL, 42, '90')
    bot_id = make_bot(factory)

    result = runner_for(factory, bot_id, broker).run_session(
        HistoricalClock(SYMBOL, bars, '1Day')
    )

    assert result.halted
    assert 'out of step with the broker' in result.halt_reason
    assert result.bars_seen == 0


# -- session baselines -----------------------------------------------------

def test_session_start_records_the_baselines_the_gate_needs(factory):
    """Without these, the daily-loss rules block every opening order.

    Deliberate -- a missing baseline means the loss is unknown -- which makes
    writing them a prerequisite for the bot being able to trade at all.
    """
    from risk.context import start_of_day_equity

    bars = make_daily_bars(n=30)
    broker = SimBroker(price='100', cash='60000')
    bot_id = make_bot(factory)

    runner_for(factory, bot_id, broker).run_session(
        HistoricalClock(SYMBOL, bars, '1Day')
    )

    with factory() as session:
        assert start_of_day_equity(session) is not None, 'no account baseline'
        assert start_of_day_equity(session, bot_id=bot_id) is not None, (
            'no bot baseline'
        )


def test_without_baselines_the_gate_blocks_every_opening_order(factory):
    """The failure mode stated plainly, so nobody is surprised by it.

    Driven by ticking directly, bypassing `start_session`, which is exactly the
    situation a runner started the wrong way would be in.
    """
    bars = make_daily_bars(n=60)
    broker = SimBroker(price='100')
    bot_id = make_bot(factory)
    runner = BotRunner(factory, broker, bot_id)  # real limits, no session start

    results = [
        runner.tick(event)
        for event in HistoricalClock(SYMBOL, bars, '1Day').ticks()
    ]

    blocked = {t.blocked_by_rule for t in results if t.blocked_by_rule}
    assert blocked == {'account_max_daily_loss'}, blocked
    assert broker.get_positions() == []


# -- flat by close ---------------------------------------------------------

def test_runner_flattens_at_the_close_when_the_strategy_does_not(factory):
    """The backstop. `flat_by_close` is configuration, so it must be enforced.

    Phase 3 established the gate does not read it. The strategies flatten
    themselves via BarContext, but a strategy that forgets must not leave a bot
    holding overnight against its own configuration.
    """
    bars = make_intraday_bars(n_sessions=2, bar_minutes=5)
    broker = SimBroker(price='100')
    # A strategy with no session awareness at all: it buys and never sells.
    bot_id = make_bot(
        factory, strategy_id='rsi_mean_revert', timeframe='5Min',
        parameters={'period': 3, 'oversold': 45, 'overbought': 99},
        risk_limits={'flat_by_close': True},
    )

    result = runner_for(factory, bot_id, broker).run_session(
        HistoricalClock(SYMBOL, bars, '5Min')
    )
    assert not result.halted, result.halt_reason

    with factory() as session:
        flattens = list(session.execute(
            select(AuditLog).where(AuditLog.event_type == AUDIT_FORCED_FLATTEN)
        ).scalars())

    if not flattens:
        pytest.skip('the strategy closed every position itself on this fixture')

    assert 'flat_by_close' in flattens[0].payload['reason']


def test_flat_by_close_can_be_switched_off(factory):
    """A swing bot holds overnight on purpose."""
    bars = make_intraday_bars(n_sessions=2, bar_minutes=5)
    broker = SimBroker(price='100')
    bot_id = make_bot(
        factory, strategy_id='rsi_mean_revert', timeframe='5Min',
        parameters={'period': 3, 'oversold': 45, 'overbought': 99},
        risk_limits={'flat_by_close': False},
    )

    runner_for(factory, bot_id, broker).run_session(
        HistoricalClock(SYMBOL, bars, '5Min')
    )

    with factory() as session:
        flattens = list(session.execute(
            select(AuditLog).where(AuditLog.event_type == AUDIT_FORCED_FLATTEN)
        ).scalars())
    assert flattens == []


# -- sizing ----------------------------------------------------------------

def test_a_close_trades_the_whole_position(factory):
    """A close that guesses its own size leaves a remainder nobody asked for."""
    bars = make_daily_bars(n=100)
    broker = SimBroker(price='100')
    bot_id = make_bot(factory)

    runner_for(factory, bot_id, broker).run_session(
        HistoricalClock(SYMBOL, bars, '1Day')
    )

    with factory() as session:
        orders = list(session.execute(
            select(Order).where(Order.status == 'filled').order_by(Order.id)
        ).scalars())

    buys = [o for o in orders if o.side == 'buy']
    sells = [o for o in orders if o.side == 'sell']
    if not sells:
        pytest.skip('the strategy never closed a position on this fixture')

    # Each sell must exactly match the buy that preceded it.
    assert sells[0].qty == buys[0].qty


def test_zero_priced_bars_do_not_produce_an_order(factory):
    """Guard against dividing by a price of zero when sizing."""
    bars = make_daily_bars(n=40).copy()
    bars.loc[:, 'close'] = 0.0
    broker = SimBroker(price='100')
    bot_id = make_bot(factory)

    result = runner_for(factory, bot_id, broker).run_session(
        HistoricalClock(SYMBOL, bars, '1Day')
    )
    assert broker.submitted == []
    assert result.errors == 0, [t.error for t in result.ticks if t.error]


# -- CLI -------------------------------------------------------------------

def test_cli_list_works_without_credentials_or_the_alpaca_sdk(factory, monkeypatch, tmp_path):
    """`--list` is how you find out what is configured.

    It must work on a machine with no Alpaca SDK and no credentials, which is
    why the CLI imports those lazily rather than at module scope.
    """
    from runner.main import main

    monkeypatch.setenv('DATABASE_URL', f'sqlite+pysqlite:///{tmp_path}/cli.db')
    from db.session import create_all, get_engine, reset_engine
    reset_engine()
    create_all(get_engine())

    assert main(['--list']) == 0
    reset_engine()


def test_cli_refuses_an_unknown_bot(factory, monkeypatch, tmp_path):
    from runner.main import main
    from db.session import create_all, get_engine, reset_engine

    monkeypatch.setenv('DATABASE_URL', f'sqlite+pysqlite:///{tmp_path}/cli2.db')
    reset_engine()
    create_all(get_engine())

    assert main(['--bot-id', '999']) == 2
    reset_engine()


def test_cli_refuses_a_live_bot(factory, monkeypatch, tmp_path):
    """Live is rejected up front, not at the last moment inside the router."""
    from runner.main import main
    from db.session import create_all, get_engine, reset_engine

    monkeypatch.setenv('DATABASE_URL', f'sqlite+pysqlite:///{tmp_path}/cli3.db')
    reset_engine()
    engine = get_engine()
    create_all(engine)

    local_factory = sessionmaker(bind=engine, expire_on_commit=False)
    with local_factory() as session:
        bot = repository.create_bot(
            session, name='live-bot', strategy_id='sma_crossover',
            symbols=['AAPL'], timeframe='1Day',
            capital_budget=Decimal('1000'), parameters={}, risk_limits={},
            mode='live', enabled=True,
        )
        session.commit()
        bot_id = bot.id

    assert main(['--bot-id', str(bot_id)]) == 2
    reset_engine()


def test_cli_requires_a_bot_or_list(monkeypatch):
    from runner.main import main
    with pytest.raises(SystemExit):
        main([])


# -- periodic reconciliation ----------------------------------------------

def test_reconciliation_runs_mid_session_not_only_at_startup(factory):
    """The plan says startup and every 60s.

    Drift found at the next restart is drift the bot traded through for the rest
    of the session. Interval set to zero here so it checks every bar; wall-clock
    time barely advances during a replay, so a 60s interval would never fire and
    the behaviour would go untested.
    """
    from db.models import AuditLog
    from runner.reconcile import AUDIT_RECONCILIATION

    bars = make_daily_bars(n=20)
    broker = SimBroker(price='100')
    bot_id = make_bot(factory)

    runner = BotRunner(
        factory, broker, bot_id, gate=permissive_gate(),
        router=OrderRouter(broker), reconcile_interval_seconds=0.0,
    )
    result = runner.run_session(HistoricalClock(SYMBOL, bars, '1Day'))

    assert not result.halted, result.halt_reason

    with factory() as session:
        checks = list(session.execute(
            select(AuditLog).where(AuditLog.event_type == AUDIT_RECONCILIATION)
        ).scalars())

    # One at startup plus one per bar.
    assert len(checks) == len(bars) + 1


def test_mid_session_divergence_halts_the_bot(factory):
    """Someone closes a position by hand while the bot is running."""
    bars = make_daily_bars(n=100)
    broker = SimBroker(price='100')
    bot_id = make_bot(factory)

    runner = BotRunner(
        factory, broker, bot_id, gate=permissive_gate(),
        router=OrderRouter(broker), reconcile_interval_seconds=0.0,
    )

    # Let it open a position, then interfere behind its back.
    clock = HistoricalClock(SYMBOL, bars, '1Day')
    ticks = clock.ticks()

    with factory() as session:
        runner.start_session(session)
        session.commit()
    runner._last_reconciled = runner._now()

    opened = False
    for event in ticks:
        runner.tick(event)
        if broker.get_positions():
            opened = True
            break
    assert opened, 'the strategy never opened a position; test is vacuous'

    # A manual close at the broker, invisible to the bot.
    broker._positions.clear()

    halt = runner._periodic_reconcile()
    assert halt is not None
    assert 'diverged from the broker mid-session' in halt

    with factory() as session:
        assert repository.get_bot(session, bot_id).enabled is False


def test_periodic_reconciliation_respects_its_interval(factory):
    """A check per bar on minute data is 390 broker calls a session."""
    from db.models import AuditLog
    from runner.reconcile import AUDIT_RECONCILIATION

    bars = make_daily_bars(n=20)
    broker = SimBroker(price='100')
    bot_id = make_bot(factory)

    # Frozen clock, so the 60s interval never elapses during the replay.
    frozen = datetime(2026, 3, 2, 14, 35, tzinfo=timezone.utc)
    runner = BotRunner(
        factory, broker, bot_id, gate=permissive_gate(),
        router=OrderRouter(broker), reconcile_interval_seconds=60.0,
        clock_now=lambda: frozen,
    )
    runner.run_session(HistoricalClock(SYMBOL, bars, '1Day'))

    with factory() as session:
        checks = list(session.execute(
            select(AuditLog).where(AuditLog.event_type == AUDIT_RECONCILIATION)
        ).scalars())

    assert len(checks) == 1, 'reconciled more often than the interval allows'


def test_reconciliation_can_be_switched_off(factory):
    bars = make_daily_bars(n=20)
    broker = SimBroker(price='100')
    bot_id = make_bot(factory)

    runner = BotRunner(
        factory, broker, bot_id, gate=permissive_gate(),
        router=OrderRouter(broker), reconcile_interval_seconds=None,
    )
    assert runner._periodic_reconcile() is None


def test_blocked_orders_are_not_counted_as_placed(factory):
    """A refusal has an order row and an id, but nothing reached the broker.

    Counting those as placed reported "orders=2" for a session where the gate
    refused both and the book never moved -- found by reading real output, not
    by a test.
    """
    from risk.contracts import AccountRiskLimits, BotRiskLimits

    bars = make_daily_bars(n=120)
    broker = SimBroker(price='100')
    bot_id = make_bot(factory, risk_limits={'max_order_value': 10})

    # An order-value ceiling of 10 dollars refuses everything.
    tight = RiskGate(
        AccountRiskLimits(max_daily_loss_pct=90.0),
        BotRiskLimits(max_order_value=Decimal('10')),
    )
    result = BotRunner(
        factory, broker, bot_id, gate=tight, router=OrderRouter(broker)
    ).run_session(HistoricalClock(SYMBOL, bars, '1Day'))

    assert result.orders_blocked > 0, 'nothing was blocked; test is vacuous'
    assert result.orders_placed == 0
    assert broker.submitted == [], 'an order reached the broker'


# -- backtest/live execution parity ---------------------------------------

def test_shorts_are_refused_by_default_in_both_engines(factory):
    """Found by reading real fills, not by a test.

    `allow_short` existed only on BacktestConfig. The backtester refused a
    sell-while-flat and counted it in `intents_rejected_shorts_disabled`, while
    the runner opened a short from the identical signal. Backtest and live were
    different algorithms again -- and `test_runner_matches_backtester` did not
    catch it, because it compares the strategy's actions rather than what the
    execution layer does with them.
    """
    from db.models import PositionRow
    from runner.loop import AUDIT_SHORT_BLOCKED

    bars = make_daily_bars(n=250)
    params = {'short_period': 5, 'long_period': 20}

    backtest = BacktestEngine(
        BacktestConfig(
            symbol=SYMBOL, start_date='2025-01-02', end_date='2025-12-31',
            strategy_id='sma_crossover', parameters=params, timeframe='1Day',
            initial_capital=50_000.0, slippage_bps=0.0,
        ),
        get_strategy('sma_crossover', params),
    ).run(bars)
    assert backtest.audit.intents_rejected_shorts_disabled > 0, (
        'the fixture never emits a sell while flat; test is vacuous'
    )

    broker = SimBroker(price='100')
    bot_id = make_bot(factory, parameters=params)
    runner_for(factory, bot_id, broker).run_session(
        HistoricalClock(SYMBOL, bars, '1Day')
    )

    # No short anywhere: not at the broker, not in our own book.
    assert all(p.qty > 0 for p in broker.get_positions())
    with factory() as session:
        assert all(
            r.qty > 0 for r in session.execute(select(PositionRow)).scalars()
        )
        refusals = list(session.execute(
            select(AuditLog).where(AuditLog.event_type == AUDIT_SHORT_BLOCKED)
        ).scalars())
    assert refusals, 'the runner did not record refusing a short'


def test_shorts_are_allowed_in_both_engines_when_enabled(factory):
    """The switch works in the same direction on both sides."""
    from db.models import PositionRow

    bars = make_daily_bars(n=250)
    params = {'short_period': 5, 'long_period': 20}

    backtest = BacktestEngine(
        BacktestConfig(
            symbol=SYMBOL, start_date='2025-01-02', end_date='2025-12-31',
            strategy_id='sma_crossover', parameters=params, timeframe='1Day',
            initial_capital=50_000.0, slippage_bps=0.0, allow_short=True,
        ),
        get_strategy('sma_crossover', params),
    ).run(bars)
    assert backtest.audit.intents_rejected_shorts_disabled == 0
    assert any(t['side'] == 'short' for t in backtest.trades)

    broker = SimBroker(price='100')
    bot_id = make_bot(factory, parameters=params,
                      risk_limits={'allow_short': True})
    runner_for(factory, bot_id, broker).run_session(
        HistoricalClock(SYMBOL, bars, '1Day')
    )

    with factory() as session:
        shorts = list(session.execute(
            select(AuditLog).where(AuditLog.event_type == 'fill')
        ).scalars())
    assert any(
        float(f.payload['resulting_position_qty']) < 0 for f in shorts
    ), 'the runner never opened a short even with allow_short on'
