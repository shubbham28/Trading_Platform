"""
The live approval queue.

D3: live orders are approval-gated until a flag is deliberately flipped. This is
the queue and the flag.

WHY REQUESTS EXPIRE.

An approval request is a question about a specific bar. Approving one that has
sat for three hours means placing an order on information the strategy would no
longer act on -- the crossover it saw has probably reversed, and nobody looking
at the queue can tell. So a request past `approval_timeout_seconds` expires
unapproved rather than waiting to be found.

That makes an unattended queue fail closed. Nothing trades, which is the correct
outcome when the person the design depends on is not there.

WHY THE FLAG NEEDS A NOTE.

`auto_approve` removes the only human check on live orders. Turning it on
without a recorded reason leaves nothing to review afterwards, and this is the
single most consequential setting in the system. The database enforces it: the
check constraint refuses an engaged flag with no note.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models import LiveSettings, Order
from db.repository import append_audit

AUDIT_APPROVAL_REQUESTED = 'approval_requested'
AUDIT_APPROVAL_GRANTED = 'approval_granted'
AUDIT_APPROVAL_DENIED = 'approval_denied'
AUDIT_APPROVAL_EXPIRED = 'approval_expired'
AUDIT_LIVE_SETTINGS = 'live_settings_changed'


class ApprovalError(RuntimeError):
    """An approval action that cannot be performed as asked."""


def get_live_settings(session: Session) -> LiveSettings:
    """The singleton, created in its safest state if absent.

    Never returns None. A missing row must not be readable as "auto-approve is
    fine" at a call site deciding whether a live order needs a person.
    """
    settings = session.get(LiveSettings, 1)
    if settings is None:
        settings = LiveSettings(
            id=1, auto_approve=False, max_order_value=Decimal('0'),
            approval_timeout_seconds=300,
        )
        session.add(settings)
        session.flush()
    return settings


def update_live_settings(
    session: Session,
    auto_approve: Optional[bool] = None,
    max_order_value: Optional[Decimal] = None,
    approval_timeout_seconds: Optional[int] = None,
    note: Optional[str] = None,
) -> LiveSettings:
    """Change the live-trading posture. Every change is audited.

    Enabling `auto_approve` requires a note. Disabling it does not -- turning a
    safety check back on should never be harder than turning it off.
    """
    settings = get_live_settings(session)
    before = {
        'auto_approve': settings.auto_approve,
        'max_order_value': str(settings.max_order_value),
        'approval_timeout_seconds': settings.approval_timeout_seconds,
    }

    if auto_approve is not None and auto_approve != settings.auto_approve:
        if auto_approve:
            if not (note or '').strip():
                raise ApprovalError(
                    'enabling auto-approve requires a note. It removes the only '
                    'human check on live orders, and a change with no recorded '
                    'reason leaves nothing to review afterwards.'
                )
            settings.auto_approve = True
            settings.auto_approve_note = note.strip()
            settings.auto_approve_enabled_at = datetime.now(timezone.utc)
        else:
            settings.auto_approve = False
            settings.auto_approve_note = None
            settings.auto_approve_enabled_at = None

    if max_order_value is not None:
        if max_order_value < 0:
            raise ApprovalError('the live order ceiling cannot be negative')
        settings.max_order_value = max_order_value

    if approval_timeout_seconds is not None:
        if approval_timeout_seconds <= 0:
            raise ApprovalError(
                'the approval timeout must be positive. A timeout of zero would '
                'expire every request before anyone could see it.'
            )
        settings.approval_timeout_seconds = approval_timeout_seconds

    session.flush()
    append_audit(
        session, event_type=AUDIT_LIVE_SETTINGS,
        payload={
            'before': before,
            'after': {
                'auto_approve': settings.auto_approve,
                'max_order_value': str(settings.max_order_value),
                'approval_timeout_seconds': settings.approval_timeout_seconds,
            },
            'note': note,
        },
    )
    return settings


def request_approval(session: Session, order: Order) -> Order:
    """Park a live order and record that a person was asked."""
    now = datetime.now(timezone.utc)
    order.status = 'awaiting_approval'
    order.approval_requested_at = now
    session.flush()

    append_audit(
        session, event_type=AUDIT_APPROVAL_REQUESTED,
        payload={
            'order_id': order.id,
            'client_order_id': order.client_order_id,
            'symbol': order.symbol,
            'side': order.side,
            'qty': str(order.qty),
            'reason': order.reason,
            'requested_at': now.isoformat(),
        },
        bot_id=order.bot_id, symbol=order.symbol,
    )
    return order


def _age_seconds(order: Order, now: datetime) -> float:
    requested = order.approval_requested_at
    if requested is None:
        return 0.0
    if requested.tzinfo is None:
        requested = requested.replace(tzinfo=timezone.utc)
    return (now - requested).total_seconds()


def expire_stale_approvals(
    session: Session, now: Optional[datetime] = None
) -> list:
    """Expire requests nobody acted on in time. Returns the expired orders.

    Called before the queue is read and before an approval is granted, so a
    stale request cannot be approved by someone who happened to have the page
    open. The alternative is a queue that quietly accumulates orders which look
    actionable and are not.
    """
    moment = now or datetime.now(timezone.utc)
    settings = get_live_settings(session)
    cutoff = settings.approval_timeout_seconds

    pending = list(session.execute(
        select(Order).where(Order.status == 'awaiting_approval')
    ).scalars())

    expired = []
    for order in pending:
        age = _age_seconds(order, moment)
        if age < cutoff:
            continue
        order.status = 'expired'
        expired.append(order)
        append_audit(
            session, event_type=AUDIT_APPROVAL_EXPIRED,
            payload={
                'order_id': order.id,
                'symbol': order.symbol,
                'side': order.side,
                'qty': str(order.qty),
                'age_seconds': round(age, 1),
                'timeout_seconds': cutoff,
                'reason': (
                    'nobody approved it in time. The bar that produced this '
                    'signal has passed, so placing it now would trade on '
                    'information the strategy would no longer act on.'
                ),
            },
            bot_id=order.bot_id, symbol=order.symbol,
        )

    if expired:
        session.flush()
    return expired


def pending_approvals(session: Session, now: Optional[datetime] = None) -> list:
    """Requests still actionable, oldest first.

    Expires stale ones first, so what comes back is only what can actually be
    approved. A queue that shows unapprovable rows invites someone to try.
    """
    expire_stale_approvals(session, now=now)
    return list(session.execute(
        select(Order)
        .where(Order.status == 'awaiting_approval')
        .order_by(Order.approval_requested_at.asc())
    ).scalars())


def approve(
    session: Session,
    order_id: int,
    note: Optional[str] = None,
    now: Optional[datetime] = None,
) -> Order:
    """Approve a live order for submission.

    Does not submit it -- the caller holds the broker. This marks the order
    approved and records who said so, and the router is what puts it on the wire.
    Separated because approving and submitting can fail independently, and an
    order recorded as approved that never reached the broker must be
    distinguishable from one that did.
    """
    moment = now or datetime.now(timezone.utc)
    expire_stale_approvals(session, now=moment)

    order = session.get(Order, order_id)
    if order is None:
        raise ApprovalError(f'order {order_id} does not exist')
    if order.status == 'expired':
        raise ApprovalError(
            f'order {order_id} expired before it was approved. Its signal is '
            'stale; the bot will raise a fresh request if the setup still holds.'
        )
    if order.status != 'awaiting_approval':
        raise ApprovalError(
            f'order {order_id} is {order.status!r}, not awaiting approval'
        )

    order.approved_at = moment
    order.approval_note = (note or '').strip() or None
    order.status = 'pending'
    session.flush()

    append_audit(
        session, event_type=AUDIT_APPROVAL_GRANTED,
        payload={
            'order_id': order.id,
            'client_order_id': order.client_order_id,
            'symbol': order.symbol,
            'side': order.side,
            'qty': str(order.qty),
            'note': order.approval_note,
            'waited_seconds': round(_age_seconds(order, moment), 1),
            'approved_at': moment.isoformat(),
        },
        bot_id=order.bot_id, symbol=order.symbol,
    )
    return order


def deny(
    session: Session, order_id: int, note: Optional[str] = None
) -> Order:
    """Refuse a live order. It never reaches the broker."""
    order = session.get(Order, order_id)
    if order is None:
        raise ApprovalError(f'order {order_id} does not exist')
    if order.status not in ('awaiting_approval', 'expired'):
        raise ApprovalError(
            f'order {order_id} is {order.status!r}, not awaiting approval'
        )

    order.status = 'cancelled'
    order.approval_note = (note or '').strip() or None
    session.flush()

    append_audit(
        session, event_type=AUDIT_APPROVAL_DENIED,
        payload={
            'order_id': order.id,
            'symbol': order.symbol,
            'side': order.side,
            'qty': str(order.qty),
            'note': order.approval_note,
        },
        bot_id=order.bot_id, symbol=order.symbol,
    )
    return order
