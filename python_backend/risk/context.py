"""
Assembling a RiskContext, and recording the gate's ruling.

Kept apart from the gate so the rules stay a pure function of their inputs and
can be tested without a database or a broker. This module is the part that talks
to both.

TWO MEASURES OF EXPOSURE, ON PURPOSE.

`account_exposure` is market value, taken from the broker. It answers "how much
of the market are we actually exposed to right now", which is what an
account-wide exposure ceiling is about.

`bot_exposure` is cost basis -- quantity times entry price, from our own
positions table. It answers "how much of this bot's allocation is deployed",
which is what a capital budget is about. A budget is money committed, not the
market's current opinion of what it bought.

They are different numbers answering different questions, and using market value
for a capital budget would let a bot quietly deploy more than its allocation
whenever its holdings appreciated.
"""
import uuid
from datetime import date, datetime, time, timezone
from decimal import Decimal
from typing import Optional

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.session import EXCHANGE_TZ
from brokers.base import BrokerAdapter
from db.models import AuditLog, Bot, EquitySnapshot, Order, PositionRow
from db.repository import append_audit, get_kill_switch
from risk.approvals import get_live_settings
from risk.contracts import BotRiskLimits, OrderIntent, RiskContext, RiskDecision
from risk.gate import RiskGate

AUDIT_RISK_DECISION = 'risk_decision'


def exchange_today(now: Optional[datetime] = None) -> date:
    """Today's date in the exchange's timezone.

    Not the server's date. A server in UTC rolls over at 19:00 or 20:00 New York
    time, mid-evening, which would reset a daily loss limit part-way through an
    extended-hours session.
    """
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return pd.Timestamp(moment).tz_convert(EXCHANGE_TZ).date()


def _session_start_utc(session_date: date) -> datetime:
    """Midnight exchange-local for that date, as UTC."""
    local = pd.Timestamp(datetime.combine(session_date, time(0, 0))).tz_localize(
        EXCHANGE_TZ
    )
    return local.tz_convert('UTC').to_pydatetime()


def start_of_day_equity(
    session: Session,
    bot_id: Optional[int] = None,
    session_date: Optional[date] = None,
) -> Optional[Decimal]:
    """The earliest equity snapshot recorded today, or None if there is none.

    None is a real answer meaning "today's P&L cannot be determined", and the
    daily-loss rules treat it as a reason to block rather than a reason to
    proceed. The runner is responsible for writing this at session open; see
    `record_start_of_day_equity`.
    """
    day = session_date or exchange_today()
    stmt = (
        select(EquitySnapshot.equity)
        .where(
            EquitySnapshot.captured_at >= _session_start_utc(day),
            EquitySnapshot.bot_id.is_(None) if bot_id is None
            else EquitySnapshot.bot_id == bot_id,
        )
        .order_by(EquitySnapshot.captured_at.asc())
        .limit(1)
    )
    return session.execute(stmt).scalar_one_or_none()


def latest_equity(
    session: Session,
    bot_id: Optional[int] = None,
    session_date: Optional[date] = None,
) -> Optional[Decimal]:
    """The most recent equity snapshot recorded today, or None if there is none.

    For a bot there is no live source of equity: the account's equity comes from
    the broker, but the broker has never heard of bots. So a bot's current equity
    is whatever the runner last recorded, which means the freshness of
    `bot_max_daily_loss` is exactly the runner's snapshot cadence. Phase 4 must
    snapshot per tick, not per session.
    """
    day = session_date or exchange_today()
    stmt = (
        select(EquitySnapshot.equity)
        .where(
            EquitySnapshot.captured_at >= _session_start_utc(day),
            EquitySnapshot.bot_id.is_(None) if bot_id is None
            else EquitySnapshot.bot_id == bot_id,
        )
        .order_by(EquitySnapshot.captured_at.desc(), EquitySnapshot.id.desc())
        .limit(1)
    )
    return session.execute(stmt).scalar_one_or_none()


def record_start_of_day_equity(
    session: Session,
    equity: Decimal,
    cash: Decimal,
    bot_id: Optional[int] = None,
    captured_at: Optional[datetime] = None,
) -> EquitySnapshot:
    """Write the baseline today's loss limits are measured against.

    OPERATIONAL PREREQUISITE. Until this exists for the account, and for each bot,
    the daily-loss rules block every opening order -- deliberately, because a
    missing baseline means the loss is unknown, not zero. The Phase 4 runner must
    call this at session open before it evaluates anything.
    """
    snapshot = EquitySnapshot(
        bot_id=bot_id,
        captured_at=captured_at or datetime.now(timezone.utc),
        equity=equity,
        cash=cash,
        drawdown=Decimal('0'),
    )
    session.add(snapshot)
    session.flush()
    return snapshot


def build_context(
    session: Session,
    broker: BrokerAdapter,
    bot: Bot,
    symbol: str,
    session_date: Optional[date] = None,
) -> RiskContext:
    """Snapshot everything the gate is allowed to consider, once."""
    day = session_date or exchange_today()

    switch = get_kill_switch(session)
    live = get_live_settings(session)
    account = broker.get_account()
    broker_positions = broker.get_positions()

    account_exposure = sum(
        (abs(p.market_value) for p in broker_positions), Decimal('0')
    )

    account_baseline = start_of_day_equity(session, bot_id=None, session_date=day)
    account_daily_pnl = (
        account.equity - account_baseline if account_baseline is not None else None
    )

    # Cost basis, not market value -- see the module docstring.
    bot_positions = list(session.execute(
        select(PositionRow).where(PositionRow.bot_id == bot.id)
    ).scalars())
    bot_exposure = sum(
        (abs(p.qty) * p.entry_price for p in bot_positions), Decimal('0')
    )

    # Both ends of the comparison come from the snapshots table, because there is
    # no live source of per-bot equity -- the broker does not know bots exist.
    # Either one missing means today's P&L is unknown, and the daily-loss rule
    # blocks rather than assumes.
    bot_baseline = start_of_day_equity(session, bot_id=bot.id, session_date=day)
    bot_current = latest_equity(session, bot_id=bot.id, session_date=day)
    bot_daily_pnl = (
        bot_current - bot_baseline
        if bot_baseline is not None and bot_current is not None
        else None
    )

    existing = next((p.qty for p in bot_positions if p.symbol == symbol), Decimal('0'))

    others = session.execute(
        select(PositionRow.bot_id).where(
            PositionRow.symbol == symbol, PositionRow.bot_id != bot.id
        )
    ).scalars().all()

    return RiskContext(
        kill_switch_engaged=switch.engaged,
        kill_switch_reason=switch.reason,
        live_auto_approved=live.auto_approve,
        live_max_order_value=live.max_order_value,
        account_equity=account.equity,
        account_exposure=account_exposure,
        account_open_positions=len(broker_positions),
        account_daily_pnl=account_daily_pnl,
        bot_budget=bot.capital_budget,
        bot_exposure=bot_exposure,
        bot_open_positions=len(bot_positions),
        bot_daily_pnl=bot_daily_pnl,
        existing_position_qty=existing,
        other_bots_holding_symbol=tuple(sorted(others)),
    )


def client_order_id_for(intent: OrderIntent) -> str:
    """A deterministic idempotency key for an intent.

    Derived from (bot, symbol, bar) rather than random, so a runner that restarts
    and replays a bar produces the same key and the broker deduplicates instead
    of double-filling. Manual orders have no bar to key on and get a random id.
    """
    if intent.bot_id is None or intent.bar_timestamp is None:
        return f'manual-{uuid.uuid4()}'
    stamp = intent.bar_timestamp.isoformat()
    return f'bot{intent.bot_id}-{intent.symbol}-{stamp}-{intent.side}'


def evaluate_and_record(
    session: Session,
    gate: RiskGate,
    intent: OrderIntent,
    context: RiskContext,
) -> tuple[RiskDecision, Optional[Order]]:
    """Rule on an order, then write down the ruling and its inputs.

    Every decision is audited, allowed as well as blocked. "Why did this bot do
    nothing all afternoon?" is only answerable if the passes were recorded too --
    an audit trail that only keeps refusals cannot distinguish a bot that was
    blocked from one that never had a signal.

    A blocked order is also written to `orders` with status 'blocked' and the
    rule that blocked it, so refusals are queryable alongside real orders rather
    than living only in the audit log.
    """
    decision = gate.evaluate(intent, context)

    append_audit(
        session,
        event_type=AUDIT_RISK_DECISION,
        payload=decision.as_payload(intent, context),
        bot_id=intent.bot_id,
        symbol=intent.symbol,
    )

    if decision.allowed:
        return decision, None

    if decision.rule == 'invalid_intent':
        # A caller bug, not a risk refusal. It is audited, but it does not belong
        # in `orders` -- the quantity is nonsense and the table's own check
        # constraint would reject the row.
        return decision, None

    blocked = Order(
        bot_id=intent.bot_id,
        client_order_id=client_order_id_for(intent),
        symbol=intent.symbol,
        side=intent.side,
        order_type=intent.order_type,
        qty=intent.qty,
        status='blocked',
        blocked_by_rule=decision.rule,
        mode=intent.mode,
        bar_timestamp=intent.bar_timestamp,
        reason=intent.reason,
    )
    session.add(blocked)
    session.flush()
    return decision, blocked
