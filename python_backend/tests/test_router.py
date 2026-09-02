"""
Order router tests.

Three things here are worth more than the rest: that a broker timeout cannot
produce a duplicate position, that a live order does not reach the broker while
the approval queue does not exist, and that position arithmetic is right for
shorts and flips as well as for the easy long case.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from db import repository
from db.models import Fill, Order, PositionRow
from risk.contracts import OrderIntent
from runner.router import (
    AUDIT_FILL, AUDIT_LIVE_BLOCKED, AUDIT_ORDER_SUBMITTED, OrderRouter,
    apply_fill,
)
from tests._fakes import SimBroker

BAR = datetime(2026, 3, 2, 14, 35, tzinfo=timezone.utc)


@pytest.fixture
def bot(db_session):
    return repository.create_bot(
        db_session, name='router-bot', strategy_id='sma_crossover',
        symbols=['AAPL'], timeframe='5Min', capital_budget=Decimal('50000'),
        parameters={}, risk_limits={}, enabled=True,
    )


def buy(bot_id, qty='10', price='100', mode='paper', bar=BAR) -> OrderIntent:
    return OrderIntent(
        bot_id=bot_id, symbol='AAPL', side='buy', qty=Decimal(qty),
        estimated_price=Decimal(price), reason='test', bar_timestamp=bar,
        mode=mode,
    )


# -- the happy path --------------------------------------------------------

def test_submitted_order_is_recorded_with_its_broker_id(db_session, bot):
    broker = SimBroker(price='150')
    order, refusal = OrderRouter(broker).submit(db_session, buy(bot.id))

    assert refusal is None
    assert order.status == 'filled'
    assert order.broker_order_id is not None
    assert order.submitted_at is not None
    assert order.client_order_id.startswith(f'bot{bot.id}-AAPL')


def test_fill_is_recorded_and_moves_the_position(db_session, bot):
    broker = SimBroker(price='150')
    order, _ = OrderRouter(broker).submit(db_session, buy(bot.id, qty='10'))

    fills = list(db_session.execute(
        select(Fill).where(Fill.order_id == order.id)
    ).scalars())
    assert len(fills) == 1
    assert fills[0].qty == Decimal('10')
    assert fills[0].price == Decimal('150')

    position = db_session.execute(
        select(PositionRow).where(PositionRow.bot_id == bot.id)
    ).scalar_one()
    assert position.qty == Decimal('10')
    assert position.entry_price == Decimal('150')


def test_order_and_fill_are_both_audited(db_session, bot):
    OrderRouter(SimBroker()).submit(db_session, buy(bot.id))

    submitted = repository.recent_audit(db_session, event_type=AUDIT_ORDER_SUBMITTED)
    filled = repository.recent_audit(db_session, event_type=AUDIT_FILL)
    assert len(submitted) == 1
    assert len(filled) == 1
    assert filled[0].payload['resulting_position_qty'] == '10'


def test_local_position_matches_the_broker_after_a_round_trip(db_session, bot):
    """Independently derived on both sides, then compared."""
    broker = SimBroker(price='120')
    router = OrderRouter(broker)

    router.submit(db_session, buy(bot.id, qty='25'))
    broker_qty = {p.symbol: p.qty for p in broker.get_positions()}
    local_qty = {
        r.symbol: r.qty for r in db_session.execute(select(PositionRow)).scalars()
    }
    assert broker_qty == local_qty == {'AAPL': Decimal('25')}

    sell = OrderIntent(
        bot_id=bot.id, symbol='AAPL', side='sell', qty=Decimal('25'),
        estimated_price=Decimal('130'), reason='close',
        bar_timestamp=BAR + timedelta(minutes=5),
    )
    router.submit(db_session, sell)

    assert broker.get_positions() == []
    assert list(db_session.execute(select(PositionRow)).scalars()) == []


# -- the timeout path ------------------------------------------------------

def test_a_broker_timeout_after_acceptance_does_not_duplicate_the_order(
    db_session, bot
):
    """The case that produces two positions if handled naively.

    The broker accepted the order and then the response was lost. Retrying blind
    would open a second position; looking the order up by our own id finds it.
    """
    broker = SimBroker(fail_next_submit=True, accept_before_failing=True)
    order, refusal = OrderRouter(broker).submit(db_session, buy(bot.id))

    assert refusal is None, 'an accepted order was reported as failed'
    assert order.broker_order_id is not None
    assert order.status == 'filled'
    # One position, not two.
    assert len(broker.get_positions()) == 1
    assert broker.get_positions()[0].qty == Decimal('10')


def test_a_broker_failure_before_acceptance_marks_the_order_rejected(
    db_session, bot
):
    broker = SimBroker(fail_next_submit=True, accept_before_failing=False)
    order, refusal = OrderRouter(broker).submit(db_session, buy(bot.id))

    assert refusal is not None
    assert order.status == 'rejected'
    assert order.broker_order_id is None
    assert broker.get_positions() == []


def test_resubmitting_the_same_bar_reuses_the_client_order_id(db_session, bot):
    """The broker deduplicates, so a replay cannot double-fill.

    The database's unique index stops a second row, so this checks the broker
    side of the same guarantee.
    """
    broker = SimBroker()
    router = OrderRouter(broker)
    router.submit(db_session, buy(bot.id))

    first_client_id = db_session.execute(select(Order)).scalar_one().client_order_id
    replayed = broker.submit_order(
        'AAPL', Decimal('10'), 'buy', client_order_id=first_client_id
    )

    assert len(broker.get_positions()) == 1
    assert broker.get_positions()[0].qty == Decimal('10')
    assert replayed.client_order_id == first_client_id


# -- live refusal ----------------------------------------------------------

def test_a_router_built_paper_only_refuses_a_live_order(db_session, bot):
    """The deployment-level switch, independent of the database.

    `allow_live=False` refuses regardless of what the live settings say, so a
    paper-only deployment cannot be made to trade by a misconfigured row. The
    approval queue that decides the rest lives in tests/test_live_gating.py.
    """
    broker = SimBroker(mode='live')
    order, refusal = OrderRouter(broker, allow_live=False).submit(
        db_session, buy(bot.id, mode='live')
    )

    assert order is None
    assert 'allow_live=False' in refusal
    assert broker.submitted == [], 'a live order reached the broker'
    assert repository.recent_audit(db_session, event_type=AUDIT_LIVE_BLOCKED)


def test_a_paper_intent_cannot_reach_a_live_broker(db_session, bot):
    """The mode lives on both objects so this mismatch is checkable."""
    order, refusal = OrderRouter(SimBroker(mode='live'), allow_live=True).submit(
        db_session, buy(bot.id, mode='paper')
    )
    assert order is None
    assert 'does not match broker mode' in refusal


def test_a_live_intent_cannot_reach_a_paper_broker(db_session, bot):
    order, refusal = OrderRouter(SimBroker(mode='paper'), allow_live=True).submit(
        db_session, buy(bot.id, mode='live')
    )
    assert order is None
    assert 'does not match broker mode' in refusal


# -- position arithmetic ---------------------------------------------------

def test_adding_to_a_long_averages_the_entry_price(db_session, bot):
    now = datetime.now(timezone.utc)
    apply_fill(db_session, bot.id, 'AAPL', Decimal('10'), Decimal('100'), now)
    row = apply_fill(db_session, bot.id, 'AAPL', Decimal('10'), Decimal('120'), now)

    assert row.qty == Decimal('20')
    assert row.entry_price == Decimal('110')


def test_reducing_a_long_leaves_the_entry_price_alone(db_session, bot):
    """The cost basis of what remains has not moved."""
    now = datetime.now(timezone.utc)
    apply_fill(db_session, bot.id, 'AAPL', Decimal('20'), Decimal('100'), now)
    row = apply_fill(db_session, bot.id, 'AAPL', Decimal('-5'), Decimal('180'), now)

    assert row.qty == Decimal('15')
    assert row.entry_price == Decimal('100')


def test_closing_a_position_removes_the_row(db_session, bot):
    """A flat book is the absence of a row; the table forbids qty = 0."""
    now = datetime.now(timezone.utc)
    apply_fill(db_session, bot.id, 'AAPL', Decimal('10'), Decimal('100'), now)
    assert apply_fill(
        db_session, bot.id, 'AAPL', Decimal('-10'), Decimal('105'), now
    ) is None
    assert list(db_session.execute(select(PositionRow)).scalars()) == []


def test_a_flip_resets_the_entry_price(db_session, bot):
    """Selling through a long starts a new short, not a shrunken long."""
    now = datetime.now(timezone.utc)
    apply_fill(db_session, bot.id, 'AAPL', Decimal('10'), Decimal('100'), now)
    row = apply_fill(db_session, bot.id, 'AAPL', Decimal('-30'), Decimal('90'), now)

    assert row.qty == Decimal('-20')
    assert row.entry_price == Decimal('90'), 'kept the long entry price'


def test_adding_to_a_short_averages_on_absolute_quantity(db_session, bot):
    """Short arithmetic is the mirror image, not a special case."""
    now = datetime.now(timezone.utc)
    apply_fill(db_session, bot.id, 'AAPL', Decimal('-10'), Decimal('100'), now)
    row = apply_fill(db_session, bot.id, 'AAPL', Decimal('-10'), Decimal('120'), now)

    assert row.qty == Decimal('-20')
    assert row.entry_price == Decimal('110')


def test_manual_orders_maintain_no_bot_position(db_session):
    """Nothing to attribute them to; reconciliation still sees them via the broker."""
    assert apply_fill(
        db_session, None, 'AAPL', Decimal('10'), Decimal('100'),
        datetime.now(timezone.utc),
    ) is None
