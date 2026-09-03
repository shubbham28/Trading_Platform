"""
Persistence tests.

Phase 2's exit criterion is that a backtest result survives a restart. A
file-backed SQLite database makes that testable here: run, dispose the engine,
reconnect, read it back.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.backtest import BacktestConfig, BacktestEngine
from db import repository
from db.models import AuditLog, BacktestEquityPoint, BacktestRun, Bot, KillSwitch, Order
from db.session import create_all, get_engine, session_scope
from strategies import get_strategy
from tests.conftest import make_daily_bars


def _run_a_backtest(strategy_id: str = 'sma_crossover'):
    df = make_daily_bars(n=120)
    engine = BacktestEngine(
        BacktestConfig(
            symbol='TEST', start_date='2025-01-02', end_date='2025-06-30',
            strategy_id=strategy_id, timeframe='1Day', initial_capital=10_000.0,
            commission=0.001, slippage_bps=2.0, max_position_pct=50.0,
        ),
        get_strategy(strategy_id),
    )
    return engine.run(df)


# -- the Phase 2 exit criterion --------------------------------------------

def test_backtest_result_survives_a_restart(tmp_path):
    """Write a run, drop every connection, reconnect, read it back.

    Disposing the engine and building a new one is the closest thing to a
    container restart that can be done in-process. An in-memory database would
    make this test pass while proving nothing.
    """
    url = f'sqlite+pysqlite:///{tmp_path}/restart.db'
    result = _run_a_backtest()

    first = get_engine(url)
    create_all(first)
    factory = sessionmaker(bind=first, expire_on_commit=False)
    with session_scope(factory) as session:
        run = repository.save_backtest_run(session, result)
        run_id = run.id
    first.dispose()  # every connection closed

    # A brand-new engine against the same file.
    second = get_engine(url)
    factory2 = sessionmaker(bind=second, expire_on_commit=False)
    with session_scope(factory2) as session:
        reloaded = repository.get_backtest_run(session, run_id)

        assert reloaded is not None, 'the run did not survive the restart'
        assert reloaded.strategy_id == result.strategy_id
        assert reloaded.symbol == result.symbol
        assert reloaded.timeframe == result.timeframe
        assert reloaded.metrics['total_return_pct'] == pytest.approx(
            result.total_return_pct
        )
        assert reloaded.metrics['sharpe_ratio'] == pytest.approx(result.sharpe_ratio)
        assert len(reloaded.trades) == result.total_trades

        points = repository.equity_curve_for_run(session, run_id)
        assert len(points) == len(result.equity_curve)
    second.dispose()


def test_cost_assumptions_are_stored_with_the_result(db_session):
    """A return figure is not comparable without the costs behind it."""
    result = _run_a_backtest()
    run = repository.save_backtest_run(db_session, result)

    assert run.config['commission'] == pytest.approx(0.001)
    assert run.config['slippage_bps'] == pytest.approx(2.0)
    assert run.config['max_position_pct'] == pytest.approx(50.0)
    assert run.config['allow_short'] is False
    assert run.config['initial_capital'] == pytest.approx(10_000.0)

    # Config lives in `config`, outcomes in `metrics`. Mixing them makes it
    # impossible to compare two runs without re-reading both blobs.
    assert 'commission' not in run.metrics
    assert 'sharpe_ratio' in run.metrics


def test_execution_audit_is_stored(db_session):
    """Whatever the engine could not do is stored alongside what it did."""
    result = _run_a_backtest()
    run = repository.save_backtest_run(db_session, result)

    assert 'forced_liquidations' in run.audit
    assert 'intents_unfilled_no_next_bar' in run.audit
    assert run.audit['forced_liquidations'] == result.audit.forced_liquidations


def test_equity_curve_is_stored_in_its_own_table(db_session):
    """Rows, not a jsonb blob. Order is preserved by bar_index."""
    result = _run_a_backtest()
    run = repository.save_backtest_run(db_session, result)

    count = db_session.execute(
        select(func.count()).select_from(BacktestEquityPoint)
        .where(BacktestEquityPoint.run_id == run.id)
    ).scalar_one()
    assert count == len(result.equity_curve)

    points = repository.equity_curve_for_run(db_session, run.id)
    assert [p.bar_index for p in points] == list(range(len(points)))
    assert float(points[0].equity) == pytest.approx(
        result.equity_curve[0]['equity'], rel=1e-6
    )


def test_deleting_a_run_removes_its_equity_points(db_session):
    """ON DELETE CASCADE, actually enforced.

    SQLite ignores foreign keys unless PRAGMA foreign_keys is on, which
    db.session switches on for exactly this reason -- otherwise the suite would
    pass while cascades did nothing.
    """
    result = _run_a_backtest()
    run = repository.save_backtest_run(db_session, result)
    run_id = run.id
    assert repository.equity_curve_for_run(db_session, run_id)

    db_session.delete(run)
    db_session.flush()

    assert repository.equity_curve_for_run(db_session, run_id) == []


def test_runs_list_newest_first_and_pages_by_id(db_session):
    for _ in range(5):
        repository.save_backtest_run(db_session, _run_a_backtest())

    page = repository.list_backtest_runs(db_session, limit=2)
    assert len(page) == 2
    assert page[0].id > page[1].id

    next_page = repository.list_backtest_runs(
        db_session, limit=2, before_id=page[-1].id
    )
    assert all(r.id < page[-1].id for r in next_page)


def test_runs_can_be_filtered_by_strategy(db_session):
    repository.save_backtest_run(db_session, _run_a_backtest('sma_crossover'))
    repository.save_backtest_run(db_session, _run_a_backtest('rsi_mean_revert'))

    only_rsi = repository.list_backtest_runs(db_session, strategy_id='rsi_mean_revert')
    assert [r.strategy_id for r in only_rsi] == ['rsi_mean_revert']


# -- constraints -----------------------------------------------------------

def test_backtest_dates_must_be_ordered(db_session):
    from datetime import date
    db_session.add(BacktestRun(
        strategy_id='s', symbol='X', timeframe='1Day',
        start_date=date(2026, 6, 1), end_date=date(2026, 1, 1),
        parameters={}, config={}, metrics={}, audit={}, trades=[],
    ))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_bot_capital_budget_must_be_positive(db_session):
    db_session.add(Bot(
        name='broke', strategy_id='sma_crossover', symbols=['AAPL'],
        timeframe='1Day', capital_budget=Decimal('0'), parameters={},
        risk_limits={},
    ))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_bot_names_are_unique(db_session):
    for _ in range(2):
        db_session.add(Bot(
            name='duplicate', strategy_id='sma_crossover', symbols=['AAPL'],
            timeframe='1Day', capital_budget=Decimal('1000'), parameters={},
            risk_limits={},
        ))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_bot_mode_is_constrained(db_session):
    db_session.add(Bot(
        name='weird-mode', strategy_id='sma_crossover', symbols=['AAPL'],
        timeframe='1Day', capital_budget=Decimal('1000'), parameters={},
        risk_limits={}, mode='sideways',
    ))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_blocked_order_must_name_the_rule_that_blocked_it(db_session):
    """"An order was blocked" is not actionable. Which rule blocked it is."""
    db_session.add(Order(
        client_order_id='blocked-nameless', symbol='AAPL', side='buy',
        order_type='market', qty=Decimal('1'), status='blocked',
    ))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_blocked_order_with_a_named_rule_is_accepted(db_session):
    db_session.add(Order(
        client_order_id='blocked-named', symbol='AAPL', side='buy',
        order_type='market', qty=Decimal('1'), status='blocked',
        blocked_by_rule='max_daily_loss',
    ))
    db_session.flush()  # must not raise


def test_limit_order_requires_a_limit_price(db_session):
    db_session.add(Order(
        client_order_id='limit-no-price', symbol='AAPL', side='buy',
        order_type='limit', qty=Decimal('1'),
    ))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_client_order_id_is_unique(db_session):
    for _ in range(2):
        db_session.add(Order(
            client_order_id='same-key', symbol='AAPL', side='buy',
            order_type='market', qty=Decimal('1'),
        ))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_one_order_per_bot_symbol_and_bar(db_session):
    """The idempotency guarantee: a replayed bar cannot become a second order."""
    bot = repository.create_bot(
        db_session, name='idem', strategy_id='sma_crossover', symbols=['AAPL'],
        timeframe='5Min', capital_budget=Decimal('5000'), parameters={},
        risk_limits={},
    )
    bar = datetime(2026, 3, 2, 14, 35, tzinfo=timezone.utc)

    db_session.add(Order(
        bot_id=bot.id, client_order_id='k1', symbol='AAPL', side='buy',
        order_type='market', qty=Decimal('10'), bar_timestamp=bar,
    ))
    db_session.flush()

    db_session.add(Order(
        bot_id=bot.id, client_order_id='k2', symbol='AAPL', side='buy',
        order_type='market', qty=Decimal('10'), bar_timestamp=bar,
    ))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_manual_orders_are_not_constrained_by_the_bar_index(db_session):
    """The idempotency index is partial: manual orders have no bot."""
    bar = datetime(2026, 3, 2, 14, 35, tzinfo=timezone.utc)
    for i in range(2):
        db_session.add(Order(
            bot_id=None, client_order_id=f'manual-{i}', symbol='AAPL',
            side='buy', order_type='market', qty=Decimal('1'),
            bar_timestamp=bar,
        ))
    db_session.flush()  # must not raise


def test_find_order_for_bar_reads_back_the_idempotency_key(db_session):
    bot = repository.create_bot(
        db_session, name='lookup', strategy_id='sma_crossover',
        symbols=['AAPL'], timeframe='5Min', capital_budget=Decimal('5000'),
        parameters={}, risk_limits={},
    )
    bar = datetime(2026, 3, 2, 14, 35, tzinfo=timezone.utc)
    db_session.add(Order(
        bot_id=bot.id, client_order_id='k1', symbol='AAPL', side='buy',
        order_type='market', qty=Decimal('10'), bar_timestamp=bar,
    ))
    db_session.flush()

    found = repository.find_order_for_bar(db_session, bot.id, 'AAPL', bar)
    assert found is not None and found.client_order_id == 'k1'

    other_bar = bar + timedelta(minutes=5)
    assert repository.find_order_for_bar(db_session, bot.id, 'AAPL', other_bar) is None


def test_position_quantity_cannot_be_zero(db_session):
    """A flat book is the absence of a row, not a row saying zero."""
    from db.models import PositionRow
    bot = repository.create_bot(
        db_session, name='flat', strategy_id='sma_crossover', symbols=['AAPL'],
        timeframe='1Day', capital_budget=Decimal('1000'), parameters={},
        risk_limits={},
    )
    db_session.add(PositionRow(
        bot_id=bot.id, symbol='AAPL', qty=Decimal('0'),
        entry_price=Decimal('100'), entry_time=datetime.now(timezone.utc),
    ))
    with pytest.raises(IntegrityError):
        db_session.flush()


# -- kill switch -----------------------------------------------------------

def test_kill_switch_defaults_to_disengaged_and_is_created_on_demand(db_session):
    """Never returns None.

    A missing row must not be readable as "not engaged" at a call site deciding
    whether to place an order.
    """
    switch = repository.get_kill_switch(db_session)
    assert switch.id == 1
    assert switch.engaged is False


def test_engaging_the_kill_switch_records_when(db_session):
    switch = repository.set_kill_switch(db_session, True, reason='manual halt')
    assert switch.engaged is True
    assert switch.engaged_at is not None
    assert switch.reason == 'manual halt'

    switch = repository.set_kill_switch(db_session, False)
    assert switch.engaged is False
    assert switch.engaged_at is None


def test_kill_switch_cannot_be_engaged_without_a_timestamp(db_session):
    """The constraint, not just the helper, enforces this."""
    repository.get_kill_switch(db_session)
    # A bulk update executes immediately, so the constraint fires here rather
    # than at flush time.
    with pytest.raises(IntegrityError):
        db_session.query(KillSwitch).filter_by(id=1).update(
            {'engaged': True, 'engaged_at': None}
        )


def test_kill_switch_stays_a_singleton(db_session):
    repository.get_kill_switch(db_session)
    db_session.add(KillSwitch(id=2, engaged=False))
    with pytest.raises(IntegrityError):
        db_session.flush()


# -- audit -----------------------------------------------------------------

def test_audit_entries_append_and_read_back_newest_first(db_session):
    for i in range(3):
        repository.append_audit(
            db_session, event_type='signal', payload={'i': i}, symbol='AAPL'
        )
    entries = repository.recent_audit(db_session)
    assert [e.payload['i'] for e in entries] == [2, 1, 0]


def test_audit_can_be_filtered_by_event_type(db_session):
    repository.append_audit(db_session, 'signal', {'a': 1})
    repository.append_audit(db_session, 'risk_decision', {'b': 2})

    only_risk = repository.recent_audit(db_session, event_type='risk_decision')
    assert [e.event_type for e in only_risk] == ['risk_decision']


def test_audit_survives_the_bot_it_refers_to(db_session):
    """ON DELETE SET NULL, not CASCADE.

    Deleting a bot must not delete the record of what it did. An audit trail that
    disappears with its subject is not an audit trail.
    """
    bot = repository.create_bot(
        db_session, name='doomed', strategy_id='sma_crossover',
        symbols=['AAPL'], timeframe='1Day', capital_budget=Decimal('1000'),
        parameters={}, risk_limits={},
    )
    repository.append_audit(db_session, 'signal', {'x': 1}, bot_id=bot.id)

    db_session.delete(bot)
    db_session.flush()
    db_session.expire_all()

    entries = db_session.execute(select(AuditLog)).scalars().all()
    assert len(entries) == 1
    assert entries[0].bot_id is None
    assert entries[0].payload == {'x': 1}


# -- bots ------------------------------------------------------------------

def test_bot_round_trips_as_a_config_record(db_session):
    """A bot is a row, which is what makes a new bot not a code change."""
    bot = repository.create_bot(
        db_session,
        name='vwap-aapl', strategy_id='vwap_reversion',
        parameters={'ema_fast': 20, 'ema_slow': 50},
        symbols=['AAPL', 'MSFT'], timeframe='5Min',
        capital_budget=Decimal('5000.00'),
        risk_limits={'max_position_pct': 20, 'max_daily_loss': 250},
        mode='paper',
    )
    db_session.expire_all()

    reloaded = repository.get_bot_by_name(db_session, 'vwap-aapl')
    assert reloaded is not None
    assert reloaded.strategy_id == 'vwap_reversion'
    assert reloaded.parameters == {'ema_fast': 20, 'ema_slow': 50}
    assert reloaded.symbols == ['AAPL', 'MSFT']
    assert reloaded.risk_limits['max_daily_loss'] == 250
    assert reloaded.enabled is False, 'a new bot must not start enabled'


def test_listing_enabled_bots_excludes_disabled_ones(db_session):
    repository.create_bot(
        db_session, name='on', strategy_id='sma_crossover', symbols=['A'],
        timeframe='1Day', capital_budget=Decimal('100'), parameters={},
        risk_limits={}, enabled=True,
    )
    repository.create_bot(
        db_session, name='off', strategy_id='sma_crossover', symbols=['B'],
        timeframe='1Day', capital_budget=Decimal('100'), parameters={},
        risk_limits={}, enabled=False,
    )
    assert [b.name for b in repository.list_bots(db_session, enabled_only=True)] == ['on']
    assert len(repository.list_bots(db_session)) == 2
