"""
Order routing.

Takes an intent the risk gate has already allowed, sends it to the broker, and
records what happened: the order, its fills, and the resulting position.

HOW A LIVE ORDER GETS OUT.

A live intent does not go straight to the broker. Unless `auto_approve` is on,
it is parked as `awaiting_approval` and a person has to say yes -- and if nobody
does within the timeout it expires rather than waiting to be found, because
approving a three-hour-old signal is trading on information the strategy would
no longer act on.

`auto_approve` is the flag from D3, and turning it on is a deliberate act that
demands a written note. Even then the live order ceiling still applies: the risk
gate refuses anything over it whether or not a person would have agreed. A cap a
setting can bypass is not a cap.

WHY A TIMEOUT IS NOT A FAILURE.

If `submit_order` raises, the order may still have reached the broker. Treating
that as "did not happen" and retrying is how you get two positions where you
wanted one. So a failed submit is followed by a lookup on our own
`client_order_id`: if the broker has it, the order landed and is recorded; only
if it does not is the order marked rejected.
"""
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from brokers.base import BrokerAdapter, BrokerError, BrokerOrder
from db.models import Fill, Order, PositionRow
from db.repository import append_audit
from risk.approvals import get_live_settings, request_approval
from risk.context import client_order_id_for
from risk.contracts import OrderIntent

AUDIT_ORDER_SUBMITTED = 'order_submitted'
AUDIT_ORDER_REJECTED = 'order_rejected'
AUDIT_FILL = 'fill'
AUDIT_LIVE_BLOCKED = 'live_blocked'

# Broker statuses that mean the order will not fill any further.
TERMINAL_STATUSES = frozenset({'filled', 'canceled', 'cancelled', 'expired',
                               'rejected'})


class OrderRouter:
    """Submits allowed intents and records the consequences."""

    def __init__(self, broker: BrokerAdapter, allow_live: bool = False):
        self.broker = broker
        # Phase 6 flips this on once there is an approval queue behind it.
        self.allow_live = allow_live

    def submit(
        self, session: Session, intent: OrderIntent
    ) -> tuple[Optional[Order], Optional[str]]:
        """Place an order. Returns (order, refusal_reason).

        The caller is expected to have run the risk gate already; this does not
        re-run it. Returning a reason rather than raising keeps a refusal an
        ordinary outcome the runner can record and carry on from.
        """
        if intent.mode == 'live' and not self.allow_live:
            # A deployment can refuse live trading outright, regardless of what
            # the database says. Belt and braces for a paper-only environment.
            reason = (
                'live order refused: this router was constructed with '
                'allow_live=False'
            )
            append_audit(
                session, event_type=AUDIT_LIVE_BLOCKED,
                payload={'symbol': intent.symbol, 'side': intent.side,
                         'qty': str(intent.qty), 'reason': reason},
                bot_id=intent.bot_id, symbol=intent.symbol,
            )
            return None, reason

        if intent.mode != self.broker.mode:
            # A paper intent must not reach a live broker, or the reverse. The
            # mode lives on both objects precisely so this is checkable.
            reason = (
                f'intent mode {intent.mode!r} does not match broker mode '
                f'{self.broker.mode!r}'
            )
            append_audit(
                session, event_type=AUDIT_ORDER_REJECTED,
                payload={'symbol': intent.symbol, 'reason': reason},
                bot_id=intent.bot_id, symbol=intent.symbol,
            )
            return None, reason

        client_order_id = client_order_id_for(intent)
        order = Order(
            bot_id=intent.bot_id,
            client_order_id=client_order_id,
            symbol=intent.symbol,
            side=intent.side,
            order_type=intent.order_type,
            qty=intent.qty,
            status='pending',
            mode=intent.mode,
            bar_timestamp=intent.bar_timestamp,
            reason=intent.reason,
        )
        session.add(order)
        # Written before the broker is called, so a crash between the two leaves
        # a pending row to investigate rather than an order nobody knows about.
        session.flush()

        # The approval gate. A live order stops here unless auto-approve is on;
        # `submit_approved` is what resumes it once a person has said yes.
        if intent.mode == 'live':
            settings = get_live_settings(session)
            if not settings.auto_approve:
                request_approval(session, order)
                return order, (
                    'live order parked for approval. It will expire in '
                    f'{settings.approval_timeout_seconds}s if nobody acts on it, '
                    'because its signal goes stale.'
                )

        broker_order = self._submit_to_broker(intent, client_order_id)

        if broker_order is None:
            order.status = 'rejected'
            session.flush()
            append_audit(
                session, event_type=AUDIT_ORDER_REJECTED,
                payload={'client_order_id': client_order_id,
                         'symbol': intent.symbol, 'qty': str(intent.qty)},
                bot_id=intent.bot_id, symbol=intent.symbol,
            )
            return order, 'broker rejected the order'

        order.broker_order_id = broker_order.broker_order_id
        order.status = _map_status(broker_order.status)
        order.submitted_at = broker_order.submitted_at or datetime.now(timezone.utc)
        session.flush()

        append_audit(
            session, event_type=AUDIT_ORDER_SUBMITTED,
            payload={
                'client_order_id': client_order_id,
                'broker_order_id': broker_order.broker_order_id,
                'symbol': intent.symbol, 'side': intent.side,
                'qty': str(intent.qty), 'status': order.status,
                'reason': intent.reason,
            },
            bot_id=intent.bot_id, symbol=intent.symbol,
        )

        if broker_order.filled_qty > 0:
            self._record_fill(session, order, broker_order)

        return order, None

    def submit_approved(
        self, session: Session, order: Order
    ) -> tuple[Optional[Order], Optional[str]]:
        """Put an already-approved order on the wire.

        Separate from `submit` because approval and submission fail
        independently. An order recorded as approved that never reached the
        broker has to be distinguishable from one that did, so the approval is
        committed first and this is what follows it.
        """
        if order.status != 'pending':
            return order, (
                f'order {order.id} is {order.status!r}; only an approved order '
                'is submitted this way'
            )

        intent = OrderIntent(
            bot_id=order.bot_id, symbol=order.symbol, side=order.side,
            qty=order.qty, estimated_price=Decimal('0'),
            reason=order.reason or '', order_type=order.order_type,
            bar_timestamp=order.bar_timestamp, mode=order.mode,
        )
        broker_order = self._submit_to_broker(intent, order.client_order_id)

        if broker_order is None:
            order.status = 'rejected'
            session.flush()
            append_audit(
                session, event_type=AUDIT_ORDER_REJECTED,
                payload={'client_order_id': order.client_order_id,
                         'symbol': order.symbol,
                         'note': 'approved, then rejected by the broker'},
                bot_id=order.bot_id, symbol=order.symbol,
            )
            return order, 'broker rejected the approved order'

        order.broker_order_id = broker_order.broker_order_id
        order.status = _map_status(broker_order.status)
        order.submitted_at = broker_order.submitted_at or datetime.now(timezone.utc)
        session.flush()

        append_audit(
            session, event_type=AUDIT_ORDER_SUBMITTED,
            payload={
                'client_order_id': order.client_order_id,
                'broker_order_id': broker_order.broker_order_id,
                'symbol': order.symbol, 'side': order.side,
                'qty': str(order.qty), 'status': order.status,
                'approved': True,
            },
            bot_id=order.bot_id, symbol=order.symbol,
        )

        if broker_order.filled_qty > 0:
            self._record_fill(session, order, broker_order)

        return order, None

    def _submit_to_broker(
        self, intent: OrderIntent, client_order_id: str
    ) -> Optional[BrokerOrder]:
        """Send the order, and survive not knowing whether it arrived."""
        try:
            return self.broker.submit_order(
                symbol=intent.symbol,
                qty=intent.qty,
                side=intent.side,
                order_type=intent.order_type,
                client_order_id=client_order_id,
            )
        except (BrokerError, Exception):
            # The request failed, but the order may have been accepted before
            # the failure. Ask, using our own id. Retrying blind is how one
            # intent becomes two positions.
            try:
                return self.broker.get_order_by_client_id(client_order_id)
            except Exception:
                return None

    def _record_fill(
        self, session: Session, order: Order, broker_order: BrokerOrder
    ) -> Fill:
        price = broker_order.filled_avg_price or Decimal('0')
        fill = Fill(
            order_id=order.id,
            broker_fill_id=f'{broker_order.broker_order_id}-fill',
            qty=broker_order.filled_qty,
            price=price,
            commission=Decimal('0'),
            filled_at=datetime.now(timezone.utc),
        )
        session.add(fill)
        session.flush()

        signed = (
            broker_order.filled_qty if order.side == 'buy'
            else -broker_order.filled_qty
        )
        position = apply_fill(
            session, order.bot_id, order.symbol, signed, price, fill.filled_at
        )

        append_audit(
            session, event_type=AUDIT_FILL,
            payload={
                'broker_order_id': broker_order.broker_order_id,
                'symbol': order.symbol, 'side': order.side,
                'qty': str(broker_order.filled_qty), 'price': str(price),
                'resulting_position_qty': (
                    str(position.qty) if position is not None else '0'
                ),
            },
            bot_id=order.bot_id, symbol=order.symbol,
        )
        return fill


def _map_status(broker_status: str) -> str:
    """Translate a broker status into one of ours.

    Unknown statuses map to 'submitted' rather than raising: an order that the
    broker has accepted is in flight regardless of what it calls the state, and
    dropping it because of an unrecognised label would lose track of a live
    order.
    """
    lowered = (broker_status or '').lower()
    mapping = {
        'new': 'submitted', 'accepted': 'submitted', 'pending_new': 'pending',
        'partially_filled': 'partial', 'partial': 'partial',
        'filled': 'filled', 'canceled': 'cancelled', 'cancelled': 'cancelled',
        'expired': 'expired', 'rejected': 'rejected',
    }
    return mapping.get(lowered, 'submitted')


def apply_fill(
    session: Session,
    bot_id: Optional[int],
    symbol: str,
    signed_qty: Decimal,
    price: Decimal,
    at: datetime,
) -> Optional[PositionRow]:
    """Update the local position for a fill. Returns the row, or None if flat.

    A flat book is the absence of a row, not a row saying zero -- the table has a
    `qty <> 0` check constraint for that reason. Entry price is a weighted
    average when adding to a position, unchanged when reducing (the cost basis
    of what remains has not moved), and reset when a fill flips the direction,
    because that is a new position rather than the old one shrinking.
    """
    if bot_id is None:
        # Manual orders are not attributed to a bot and so have no bot position
        # to maintain. Reconciliation still sees them via the broker.
        return None

    row = session.execute(
        select(PositionRow).where(
            PositionRow.bot_id == bot_id, PositionRow.symbol == symbol
        )
    ).scalar_one_or_none()

    if row is None:
        row = PositionRow(
            bot_id=bot_id, symbol=symbol, qty=signed_qty,
            entry_price=price, entry_time=at,
        )
        session.add(row)
        session.flush()
        return row

    new_qty = row.qty + signed_qty

    if new_qty == 0:
        session.delete(row)
        session.flush()
        return None

    flipped = (row.qty > 0) != (new_qty > 0)
    adding = abs(new_qty) > abs(row.qty)

    if flipped:
        row.entry_price = price
        row.entry_time = at
    elif adding:
        # Weighted by absolute quantity, so it works the same for a short.
        total_cost = abs(row.qty) * row.entry_price + abs(signed_qty) * price
        row.entry_price = total_cost / abs(new_qty)

    row.qty = new_qty
    row.updated_at = at
    session.flush()
    return row
