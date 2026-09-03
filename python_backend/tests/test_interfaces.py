"""
Broker and data-provider interface tests.

Both interfaces exist to be faked. An order path that can only be exercised
against a live broker will not be exercised, and the risk gate and runner in
Phases 3 and 4 are exactly the code that must not ship untested. These fakes are
the harness those phases will build on.
"""
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

import pandas as pd
import pytest

from brokers.base import (
    BrokerAccount, BrokerAdapter, BrokerError, BrokerOrder, BrokerPosition,
)
from data.base import REQUIRED_COLUMNS, DataProvider
from db.session import get_engine, reset_engine, session_scope
from tests.conftest import make_daily_bars


class FakeDataProvider(DataProvider):
    """A DataProvider backed by a fixed frame."""

    name = 'fake'

    def __init__(self, frame: Optional[pd.DataFrame] = None):
        self.frame = frame if frame is not None else make_daily_bars(n=60)
        self.calls: list[tuple] = []

    def get_bars(self, symbol, start_date, end_date, timeframe='1Day'):
        self.calls.append((symbol, start_date, end_date, timeframe))
        return self.validate_frame(self.frame)

    def get_latest_bar(self, symbol, timeframe='1Min'):
        return self.frame.iloc[-1].to_dict() if not self.frame.empty else None


class FakeBroker(BrokerAdapter):
    """An in-memory BrokerAdapter.

    Honours the idempotency contract: resending a client_order_id returns the
    existing order rather than creating a second one. A fake that quietly allows
    duplicates would let a double-submission bug pass every test.
    """

    def __init__(self, mode: str = 'paper', equity: str = '10000'):
        self.mode = mode
        self._equity = Decimal(equity)
        self._orders: dict[str, BrokerOrder] = {}
        self._by_client_id: dict[str, str] = {}
        self._positions: list[BrokerPosition] = []
        self._counter = 0
        self.submit_calls = 0

    def get_account(self):
        return BrokerAccount(
            equity=self._equity, cash=self._equity,
            buying_power=self._equity * 2,
        )

    def get_positions(self):
        return list(self._positions)

    def submit_order(
        self, symbol, qty, side, order_type='market', time_in_force='day',
        limit_price=None, stop_price=None, client_order_id=None,
    ):
        self.submit_calls += 1
        if qty <= 0:
            raise ValueError(f'qty must be positive, got {qty}')

        if client_order_id and client_order_id in self._by_client_id:
            return self._orders[self._by_client_id[client_order_id]]

        self._counter += 1
        broker_id = f'broker-{self._counter}'
        key = client_order_id or broker_id
        order = BrokerOrder(
            broker_order_id=broker_id, client_order_id=key, symbol=symbol,
            side=side, qty=Decimal(qty), filled_qty=Decimal(qty),
            status='filled', order_type=order_type,
            submitted_at=datetime(2026, 3, 2, 14, 35, tzinfo=timezone.utc),
            filled_avg_price=limit_price or Decimal('100'),
        )
        self._orders[broker_id] = order
        self._by_client_id[key] = broker_id
        return order

    def cancel_order(self, broker_order_id):
        if broker_order_id not in self._orders:
            raise BrokerError(f'unknown order {broker_order_id}')
        del self._orders[broker_order_id]

    def get_order(self, broker_order_id):
        return self._orders.get(broker_order_id)

    def get_order_by_client_id(self, client_order_id):
        broker_id = self._by_client_id.get(client_order_id)
        return self._orders.get(broker_id) if broker_id else None


# -- the interfaces are actually implementable -----------------------------

def test_fakes_satisfy_the_interfaces():
    assert isinstance(FakeBroker(), BrokerAdapter)
    assert isinstance(FakeDataProvider(), DataProvider)


def test_broker_adapter_cannot_be_instantiated_directly():
    with pytest.raises(TypeError):
        BrokerAdapter()


def test_data_provider_cannot_be_instantiated_directly():
    with pytest.raises(TypeError):
        DataProvider()


# -- data provider contract ------------------------------------------------

def test_provider_returns_the_required_columns():
    frame = FakeDataProvider().get_bars('AAPL', '2025-01-01', '2025-06-01')
    for column in REQUIRED_COLUMNS:
        assert column in frame.columns


def test_provider_rejects_a_frame_missing_required_columns():
    """A missing `volume` would silently disable every volume filter.

    Every volume comparison in every strategy would evaluate against nothing,
    and the backtest would run and report numbers. Failing loudly here is the
    difference between an exception and a quietly wrong result.
    """
    broken = make_daily_bars(n=10).drop(columns=['volume'])
    provider = FakeDataProvider(broken)
    with pytest.raises(ValueError, match='volume'):
        provider.get_bars('AAPL', '2025-01-01', '2025-06-01')


def test_empty_frame_is_a_valid_answer():
    """No data for a window is not an error."""
    provider = FakeDataProvider(pd.DataFrame())
    assert provider.get_bars('AAPL', '2025-01-01', '2025-06-01').empty


def test_provider_names_its_feed():
    """Which tape produced a number is not a detail.

    Alpaca's IEX feed is roughly 2% of consolidated volume. A result computed
    against it is not comparable to one computed against the full tape, so the
    feed identity travels with the provider.
    """
    assert FakeDataProvider().name == 'fake'


# -- broker contract -------------------------------------------------------

def test_resending_a_client_order_id_does_not_create_a_second_order():
    """The idempotency contract.

    After a network timeout the caller does not know whether the order landed.
    Resending with the same key must be safe, otherwise the only options are
    risking a duplicate or abandoning a fill.
    """
    broker = FakeBroker()
    first = broker.submit_order('AAPL', Decimal('10'), 'buy', client_order_id='k1')
    second = broker.submit_order('AAPL', Decimal('10'), 'buy', client_order_id='k1')

    assert first.broker_order_id == second.broker_order_id
    assert broker.submit_calls == 2, 'both calls should have been made'
    assert len(broker._orders) == 1, 'but only one order should exist'


def test_order_can_be_found_by_our_own_id():
    """The recovery path: did my order actually land?"""
    broker = FakeBroker()
    broker.submit_order('AAPL', Decimal('5'), 'buy', client_order_id='recover-me')

    found = broker.get_order_by_client_id('recover-me')
    assert found is not None and found.symbol == 'AAPL'
    assert broker.get_order_by_client_id('never-sent') is None


def test_zero_or_negative_quantity_is_rejected():
    broker = FakeBroker()
    for qty in (Decimal('0'), Decimal('-1')):
        with pytest.raises(ValueError):
            broker.submit_order('AAPL', qty, 'buy')


def test_cancelling_an_unknown_order_raises_broker_error():
    """Distinct from ValueError: "they said no" is not "we asked badly"."""
    with pytest.raises(BrokerError):
        FakeBroker().cancel_order('does-not-exist')


def test_broker_declares_its_mode():
    """A paper/live mix-up must be visible on the object, not inferred."""
    assert FakeBroker(mode='paper').mode == 'paper'
    assert FakeBroker(mode='live').mode == 'live'


def test_positions_carry_signed_quantities():
    """Signed quantity is what lets one code path mark longs and shorts."""
    short = BrokerPosition(
        symbol='AAPL', qty=Decimal('-10'),
        avg_entry_price=Decimal('100'), market_value=Decimal('-980'),
    )
    assert short.qty < 0
    assert short.market_value < 0


def test_blocked_account_is_visible_on_the_account_object():
    """A restricted account must not read as a merely quiet one."""
    blocked = BrokerAccount(
        equity=Decimal('1000'), cash=Decimal('1000'),
        buying_power=Decimal('0'), trading_blocked=True,
    )
    assert blocked.trading_blocked is True


# -- session semantics -----------------------------------------------------

def test_session_scope_commits_on_success(tmp_path):
    from sqlalchemy.orm import sessionmaker
    from db.repository import append_audit, recent_audit
    from db.session import create_all

    engine = get_engine(f'sqlite+pysqlite:///{tmp_path}/commit.db')
    create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    with session_scope(factory) as session:
        append_audit(session, 'signal', {'committed': True})

    with session_scope(factory) as session:
        assert len(recent_audit(session)) == 1
    engine.dispose()


def test_session_scope_rolls_back_on_failure(tmp_path):
    """A partly recorded write is a reconciliation failure waiting to happen."""
    from sqlalchemy.orm import sessionmaker
    from db.repository import append_audit, recent_audit
    from db.session import create_all

    engine = get_engine(f'sqlite+pysqlite:///{tmp_path}/rollback.db')
    create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    with pytest.raises(RuntimeError):
        with session_scope(factory) as session:
            append_audit(session, 'signal', {'should_not_persist': True})
            raise RuntimeError('boom')

    with session_scope(factory) as session:
        assert recent_audit(session) == []
    engine.dispose()


def test_default_database_url_is_not_a_silent_sqlite_fallback():
    """Defaulting to SQLite would let the app look healthy while writing
    bot state and audit rows to a local file nobody is watching."""
    from db.session import DEFAULT_DATABASE_URL
    assert DEFAULT_DATABASE_URL.startswith('postgresql')


def test_sqlite_engines_enforce_foreign_keys(tmp_path):
    """SQLite ignores foreign keys unless told otherwise.

    Without the PRAGMA, every cascade and FK test in this suite would pass while
    doing nothing -- worse than not testing them at all.
    """
    from sqlalchemy import text
    engine = get_engine(f'sqlite+pysqlite:///{tmp_path}/fk.db')
    with engine.connect() as connection:
        enabled = connection.execute(text('PRAGMA foreign_keys')).scalar()
    engine.dispose()
    assert enabled == 1


def test_reset_engine_clears_the_cached_engine():
    reset_engine()
    from db import session as session_module
    assert session_module._engine is None
