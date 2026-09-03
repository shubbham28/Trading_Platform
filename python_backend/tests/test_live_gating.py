"""
Live gating tests.

Phase 6's exit criterion, verbatim: with live keys configured and the flag off,
no order reaches the broker without an explicit approval recorded in
`audit_log`.

`SimBroker` records every order it was asked to place in `submitted`, so
"reached the broker" is a fact this suite can assert on directly rather than
infer from a status column.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from db import repository
from db.models import AuditLog, Order, PositionRow
from db.session import create_all, get_engine
from risk import approvals
from risk.approvals import (
    AUDIT_APPROVAL_DENIED, AUDIT_APPROVAL_EXPIRED, AUDIT_APPROVAL_GRANTED,
    AUDIT_APPROVAL_REQUESTED, AUDIT_LIVE_SETTINGS, ApprovalError,
)
from risk.contracts import AccountRiskLimits, BotRiskLimits, OrderIntent
from risk.gate import RiskGate
from runner.router import OrderRouter
from tests._fakes import SimBroker

BAR = datetime(2026, 3, 2, 14, 35, tzinfo=timezone.utc)


@pytest.fixture
def live_bot(db_session):
    return repository.create_bot(
        db_session, name='live-bot', strategy_id='sma_crossover',
        symbols=['AAPL'], timeframe='1Day', capital_budget=Decimal('50000'),
        parameters={}, risk_limits={}, mode='live', enabled=True,
    )


def live_intent(bot_id, qty='10', price='100', bar=BAR) -> OrderIntent:
    return OrderIntent(
        bot_id=bot_id, symbol='AAPL', side='buy', qty=Decimal(qty),
        estimated_price=Decimal(price), reason='crossover',
        bar_timestamp=bar, mode='live',
    )


def live_router(broker) -> OrderRouter:
    # allow_live=True: the deployment permits live trading, so what is under
    # test is the approval gate rather than the deployment switch.
    return OrderRouter(broker, allow_live=True)


# -- the exit criterion ----------------------------------------------------

def test_a_live_order_does_not_reach_the_broker_without_approval(
    db_session, live_bot
):
    """The criterion, stated as plainly as it can be tested.

    Live credentials present, the flag off, and the broker is never asked.
    """
    broker = SimBroker(mode='live', price='100')
    order, note = live_router(broker).submit(db_session, live_intent(live_bot.id))

    assert broker.submitted == [], 'a live order reached the broker unapproved'
    assert broker.get_positions() == []
    assert order.status == 'awaiting_approval'
    assert order.approval_requested_at is not None
    assert 'parked for approval' in note

    requested = repository.recent_audit(
        db_session, event_type=AUDIT_APPROVAL_REQUESTED
    )
    assert len(requested) == 1
    assert requested[0].payload['order_id'] == order.id


def test_approval_is_recorded_in_the_audit_log_before_the_order_goes_out(
    db_session, live_bot
):
    """"an explicit approval recorded in audit_log" -- the other half."""
    broker = SimBroker(mode='live', price='100')
    router = live_router(broker)
    order, _ = router.submit(db_session, live_intent(live_bot.id))

    approvals.approve(db_session, order.id, note='checked the tape')

    granted = repository.recent_audit(db_session, event_type=AUDIT_APPROVAL_GRANTED)
    assert len(granted) == 1
    assert granted[0].payload['order_id'] == order.id
    assert granted[0].payload['note'] == 'checked the tape'
    assert 'waited_seconds' in granted[0].payload

    # Only now does it reach the broker.
    assert broker.submitted == []
    submitted, refusal = router.submit_approved(db_session, order)
    assert refusal is None
    assert len(broker.submitted) == 1
    assert submitted.status == 'filled'
    assert submitted.broker_order_id is not None


def test_an_approved_order_fills_and_moves_the_position(db_session, live_bot):
    broker = SimBroker(mode='live', price='120')
    router = live_router(broker)
    order, _ = router.submit(db_session, live_intent(live_bot.id, qty='25'))
    approvals.approve(db_session, order.id)
    router.submit_approved(db_session, order)

    position = db_session.execute(select(PositionRow)).scalar_one()
    assert position.qty == Decimal('25')
    assert position.entry_price == Decimal('120')
    assert {p.symbol: p.qty for p in broker.get_positions()} == {'AAPL': Decimal('25')}


def test_a_rejected_order_never_reaches_the_broker(db_session, live_bot):
    broker = SimBroker(mode='live', price='100')
    order, _ = live_router(broker).submit(db_session, live_intent(live_bot.id))

    approvals.deny(db_session, order.id, note='looks like a bad print')

    assert broker.submitted == []
    assert order.status == 'cancelled'
    denied = repository.recent_audit(db_session, event_type=AUDIT_APPROVAL_DENIED)
    assert denied[0].payload['note'] == 'looks like a bad print'


# -- auto approve ----------------------------------------------------------

def test_auto_approve_sends_a_live_order_straight_through(db_session, live_bot):
    """The flag from D3, doing what it says once deliberately enabled."""
    approvals.update_live_settings(
        db_session, auto_approve=True, note='ran on paper for a month'
    )

    broker = SimBroker(mode='live', price='100')
    order, refusal = live_router(broker).submit(db_session, live_intent(live_bot.id))

    assert refusal is None
    assert len(broker.submitted) == 1
    assert order.status == 'filled'
    assert repository.recent_audit(
        db_session, event_type=AUDIT_APPROVAL_REQUESTED
    ) == []


def test_enabling_auto_approve_requires_a_note(db_session):
    """It removes the only human check on live orders.

    A change with no recorded reason leaves nothing to review afterwards, and
    this is the most consequential setting in the system.
    """
    with pytest.raises(ApprovalError, match='requires a note'):
        approvals.update_live_settings(db_session, auto_approve=True)

    with pytest.raises(ApprovalError, match='requires a note'):
        approvals.update_live_settings(db_session, auto_approve=True, note='   ')

    assert approvals.get_live_settings(db_session).auto_approve is False


def test_disabling_auto_approve_needs_no_note(db_session):
    """Turning a safety check back on must never be harder than turning it off."""
    approvals.update_live_settings(db_session, auto_approve=True, note='deliberate')
    settings = approvals.update_live_settings(db_session, auto_approve=False)

    assert settings.auto_approve is False
    assert settings.auto_approve_note is None
    assert settings.auto_approve_enabled_at is None


def test_auto_approve_defaults_to_off_and_is_never_none(db_session):
    """A missing row must not read as "auto-approve is fine"."""
    settings = approvals.get_live_settings(db_session)
    assert settings.auto_approve is False
    assert settings.max_order_value == Decimal('0')


def test_every_live_settings_change_is_audited(db_session):
    approvals.update_live_settings(
        db_session, auto_approve=True, max_order_value=Decimal('2500'),
        note='starting small',
    )
    entries = repository.recent_audit(db_session, event_type=AUDIT_LIVE_SETTINGS)
    assert len(entries) == 1
    payload = entries[0].payload
    assert payload['before']['auto_approve'] is False
    assert payload['after']['auto_approve'] is True
    assert payload['after']['max_order_value'] == '2500'
    assert payload['note'] == 'starting small'


# -- expiry ----------------------------------------------------------------

def test_a_stale_request_expires_rather_than_waiting_to_be_found(
    db_session, live_bot
):
    """Approving a three-hour-old signal is trading on stale information.

    The crossover it saw has probably reversed, and nobody looking at the queue
    can tell. So the request expires instead of sitting there looking actionable.
    """
    broker = SimBroker(mode='live', price='100')
    order, _ = live_router(broker).submit(db_session, live_intent(live_bot.id))
    assert order.status == 'awaiting_approval'

    later = datetime.now(timezone.utc) + timedelta(hours=3)
    expired = approvals.expire_stale_approvals(db_session, now=later)

    assert [o.id for o in expired] == [order.id]
    assert order.status == 'expired'
    assert broker.submitted == []

    entry = repository.recent_audit(db_session, event_type=AUDIT_APPROVAL_EXPIRED)[0]
    assert entry.payload['order_id'] == order.id
    assert 'stale' in entry.payload['reason'] or 'no longer act on' in entry.payload['reason']


def test_an_expired_request_cannot_be_approved(db_session, live_bot):
    """The race this closes: someone with the page open clicks approve on a
    row that went stale while they were reading it."""
    broker = SimBroker(mode='live', price='100')
    order, _ = live_router(broker).submit(db_session, live_intent(live_bot.id))

    later = datetime.now(timezone.utc) + timedelta(hours=3)
    with pytest.raises(ApprovalError, match='expired before it was approved'):
        approvals.approve(db_session, order.id, now=later)

    assert broker.submitted == []
    assert order.status == 'expired'


def test_a_fresh_request_is_not_expired(db_session, live_bot):
    broker = SimBroker(mode='live', price='100')
    order, _ = live_router(broker).submit(db_session, live_intent(live_bot.id))

    assert approvals.expire_stale_approvals(db_session) == []
    assert order.status == 'awaiting_approval'


def test_the_queue_only_shows_what_can_still_be_approved(db_session, live_bot):
    """A queue showing unapprovable rows invites someone to try, and the
    failure then comes at the click rather than on the screen."""
    broker = SimBroker(mode='live', price='100')
    router = live_router(broker)

    stale, _ = router.submit(db_session, live_intent(live_bot.id, bar=BAR))
    fresh, _ = router.submit(
        db_session, live_intent(live_bot.id, bar=BAR + timedelta(minutes=5))
    )
    # Backdate one request beyond the timeout.
    stale.approval_requested_at = datetime.now(timezone.utc) - timedelta(hours=1)
    db_session.flush()

    queue = approvals.pending_approvals(db_session)
    assert [o.id for o in queue] == [fresh.id]
    assert stale.status == 'expired'


def test_the_queue_is_oldest_first(db_session, live_bot):
    """Whatever is closest to expiring needs attention first."""
    broker = SimBroker(mode='live', price='100')
    router = live_router(broker)
    now = datetime.now(timezone.utc)

    orders = []
    for index in range(3):
        order, _ = router.submit(
            db_session,
            live_intent(live_bot.id, bar=BAR + timedelta(minutes=5 * index)),
        )
        order.approval_requested_at = now - timedelta(seconds=30 * (3 - index))
        orders.append(order)
    db_session.flush()

    queue = approvals.pending_approvals(db_session)
    assert [o.id for o in queue] == [orders[0].id, orders[1].id, orders[2].id]


def test_a_zero_timeout_is_refused(db_session):
    """It would expire every request before anyone could see it."""
    with pytest.raises(ApprovalError, match='must be positive'):
        approvals.update_live_settings(db_session, approval_timeout_seconds=0)


# -- interaction with the rest of the system ------------------------------

def test_the_kill_switch_still_stops_a_live_order_before_approval(
    db_session, live_bot
):
    """The gate runs first, so an approval is never even requested."""
    repository.set_kill_switch(db_session, True, reason='halt')
    approvals.update_live_settings(
        db_session, max_order_value=Decimal('100000'), auto_approve=True,
        note='deliberate',
    )

    from risk.context import build_context, evaluate_and_record

    broker = SimBroker(mode='live', price='100')
    ctx = build_context(db_session, broker, live_bot, 'AAPL')
    decision, blocked = evaluate_and_record(
        db_session,
        RiskGate(AccountRiskLimits(max_daily_loss_pct=90.0), BotRiskLimits()),
        live_intent(live_bot.id), ctx,
    )

    assert decision.blocked
    assert decision.rule == 'account_kill_switch'
    assert repository.recent_audit(
        db_session, event_type=AUDIT_APPROVAL_REQUESTED
    ) == []


def test_the_live_ceiling_refuses_before_a_person_is_asked(db_session, live_bot):
    """A ceiling breach is not a question for anybody.

    Asking someone to approve an order the ceiling forbids wastes their
    attention and invites them to wonder whether the ceiling is negotiable.
    """
    from risk.context import build_context, evaluate_and_record

    approvals.update_live_settings(db_session, max_order_value=Decimal('500'))
    broker = SimBroker(mode='live', price='100')
    ctx = build_context(db_session, broker, live_bot, 'AAPL')

    decision, blocked = evaluate_and_record(
        db_session,
        RiskGate(AccountRiskLimits(max_daily_loss_pct=90.0), BotRiskLimits()),
        live_intent(live_bot.id, qty='100'), ctx,   # 10000 notional
    )

    assert decision.blocked
    assert decision.rule == 'account_live_order_ceiling'
    assert blocked.status == 'blocked'
    assert repository.recent_audit(
        db_session, event_type=AUDIT_APPROVAL_REQUESTED
    ) == []


def test_a_paper_order_is_never_parked(db_session):
    """Paper is the whole point of paper. It does not wait for anyone."""
    paper_bot = repository.create_bot(
        db_session, name='paper-bot', strategy_id='sma_crossover',
        symbols=['AAPL'], timeframe='1Day', capital_budget=Decimal('50000'),
        parameters={}, risk_limits={}, mode='paper', enabled=True,
    )
    broker = SimBroker(mode='paper', price='100')
    intent = OrderIntent(
        bot_id=paper_bot.id, symbol='AAPL', side='buy', qty=Decimal('10'),
        estimated_price=Decimal('100'), reason='test', bar_timestamp=BAR,
        mode='paper',
    )

    order, refusal = OrderRouter(broker).submit(db_session, intent)
    assert refusal is None
    assert order.status == 'filled'
    assert len(broker.submitted) == 1


def test_a_deployment_can_refuse_live_trading_outright(db_session, live_bot):
    """Belt and braces for a paper-only environment.

    `allow_live=False` refuses regardless of what the database says, so a
    misconfigured settings row cannot make a paper-only deployment trade.
    """
    approvals.update_live_settings(
        db_session, auto_approve=True, max_order_value=Decimal('100000'),
        note='deliberate',
    )
    broker = SimBroker(mode='live', price='100')

    order, refusal = OrderRouter(broker, allow_live=False).submit(
        db_session, live_intent(live_bot.id)
    )
    assert order is None
    assert 'allow_live=False' in refusal
    assert broker.submitted == []


def test_submit_approved_refuses_an_unapproved_order(db_session, live_bot):
    """The submission path cannot be used to skip the queue."""
    broker = SimBroker(mode='live', price='100')
    router = live_router(broker)
    order, _ = router.submit(db_session, live_intent(live_bot.id))

    assert order.status == 'awaiting_approval'
    submitted, refusal = router.submit_approved(db_session, order)
    assert 'only an approved order' in refusal
    assert broker.submitted == []


def test_an_approved_order_the_broker_rejects_is_distinguishable(
    db_session, live_bot
):
    """Approved-then-refused is not the same as never approved.

    The approval is committed before submission is attempted precisely so these
    two outcomes can be told apart afterwards.
    """
    broker = SimBroker(mode='live', price='100', fail_next_submit=True)
    router = live_router(broker)
    order, _ = router.submit(db_session, live_intent(live_bot.id))
    approvals.approve(db_session, order.id, note='fine by me')

    submitted, refusal = router.submit_approved(db_session, order)
    assert refusal is not None
    assert submitted.status == 'rejected'
    # The approval survives the rejection.
    assert submitted.approved_at is not None
    assert repository.recent_audit(db_session, event_type=AUDIT_APPROVAL_GRANTED)


def test_approving_a_nonexistent_order_is_an_error_not_a_silent_pass(db_session):
    with pytest.raises(ApprovalError, match='does not exist'):
        approvals.approve(db_session, 999999)
