"""
Repository functions.

Thin, explicit functions rather than a generic DAO. Each one names a real
operation the system performs, so a reader can see the whole set of things that
touch the database in one file.
"""
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Iterable, Optional

from sqlalchemy import insert, select
from sqlalchemy.orm import Session, selectinload

from db.models import (
    AuditLog, BacktestEquityPoint, BacktestRun, Bot, KillSwitch, Order,
)

# Fields of a BacktestResult that describe the run's identity or its cost
# assumptions rather than its outcome. Separated so `metrics` holds only results
# and `config` holds only what produced them.
_IDENTITY_FIELDS = frozenset({
    'strategy_id', 'symbol', 'start_date', 'end_date', 'timeframe',
    'parameters',
})
_CONFIG_FIELDS = frozenset({
    'initial_capital', 'commission', 'slippage_bps', 'max_position_pct',
    'allow_short',
})
_BULK_FIELDS = frozenset({'trades', 'equity_curve', 'audit'})
# Set by the persistence layer itself. Storing them inside `metrics` would file
# bookkeeping next to Sharpe ratios and win rates.
_PERSISTENCE_FIELDS = frozenset({'run_id', 'persisted', 'persistence_error'})


def _as_date(value: Any) -> date:
    """Coerce the engine's ISO date strings into real dates."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def save_backtest_run(session: Session, result: Any) -> BacktestRun:
    """Persist a BacktestResult and its equity curve.

    `result` is the pydantic BacktestResult from app.backtest. Splitting it into
    identity, config, metrics and audit is deliberate: a Sharpe ratio filed
    without the slippage and sizing that produced it is not comparable to
    anything, so the cost assumptions are stored as first-class columns of the
    record rather than left in a log line.
    """
    if hasattr(result, 'model_dump'):
        # Two dumps on purpose. `mode='json'` coerces pandas Timestamps and
        # Decimals into JSON-safe primitives, which the jsonb columns require --
        # a trade list straight out of the engine carries pd.Timestamp objects
        # and fails to serialise. The plain dump keeps real datetimes, which is
        # what the equity points' timestamptz column needs.
        payload = result.model_dump(mode='json')
        native = result.model_dump()
    else:
        payload = native = dict(result)

    excluded = (
        _IDENTITY_FIELDS | _CONFIG_FIELDS | _BULK_FIELDS | _PERSISTENCE_FIELDS
    )
    metrics = {k: v for k, v in payload.items() if k not in excluded}
    config = {k: payload[k] for k in _CONFIG_FIELDS if k in payload}

    run = BacktestRun(
        strategy_id=payload['strategy_id'],
        symbol=payload['symbol'],
        timeframe=payload.get('timeframe', '1Day'),
        start_date=_as_date(payload['start_date']),
        end_date=_as_date(payload['end_date']),
        parameters=payload.get('parameters') or {},
        config=config,
        metrics=metrics,
        audit=payload.get('audit') or {},
        trades=payload.get('trades') or [],
    )
    session.add(run)
    # Need the generated id before the equity rows can reference it.
    session.flush()

    # From `native`, not `payload`: the timestamptz column wants datetimes.
    equity_curve = native.get('equity_curve') or []
    if equity_curve:
        _bulk_insert_equity(session, run.id, equity_curve)

    return run


def _bulk_insert_equity(
    session: Session, run_id: int, equity_curve: Iterable[dict]
) -> None:
    """Insert equity points in one statement rather than one per point.

    A year of one-minute bars is roughly 98,000 points. As individual ORM inserts
    that is 98,000 round trips and a backtest that appears to hang; as a single
    executemany it is one statement. This is why the equity curve is its own
    table and not a jsonb blob on the run.
    """
    rows = [
        {
            'run_id': run_id,
            'bar_index': i,
            'timestamp': point['timestamp'],
            'equity': Decimal(str(point['equity'])),
            'drawdown': Decimal(str(point.get('drawdown', 0))),
        }
        for i, point in enumerate(equity_curve)
    ]
    session.execute(insert(BacktestEquityPoint), rows)


def get_backtest_run(
    session: Session, run_id: int, with_equity: bool = False
) -> Optional[BacktestRun]:
    stmt = select(BacktestRun).where(BacktestRun.id == run_id)
    if with_equity:
        # Eager-load in one extra query rather than lazily per point, which
        # would be an N+1 over the whole curve.
        stmt = stmt.options(selectinload(BacktestRun.equity_points))
    return session.execute(stmt).scalar_one_or_none()


def list_backtest_runs(
    session: Session,
    strategy_id: Optional[str] = None,
    symbol: Optional[str] = None,
    limit: int = 50,
    before_id: Optional[int] = None,
) -> list[BacktestRun]:
    """Most recent runs first.

    Paged by `before_id` rather than OFFSET: keyset pagination stays fast at any
    depth, where OFFSET has to walk and discard every row it skips.
    """
    stmt = select(BacktestRun).order_by(BacktestRun.id.desc()).limit(limit)
    if strategy_id:
        stmt = stmt.where(BacktestRun.strategy_id == strategy_id)
    if symbol:
        stmt = stmt.where(BacktestRun.symbol == symbol)
    if before_id is not None:
        stmt = stmt.where(BacktestRun.id < before_id)
    return list(session.execute(stmt).scalars())


def equity_curve_for_run(
    session: Session, run_id: int, limit: Optional[int] = None
) -> list[BacktestEquityPoint]:
    stmt = (
        select(BacktestEquityPoint)
        .where(BacktestEquityPoint.run_id == run_id)
        .order_by(BacktestEquityPoint.bar_index)
    )
    if limit is not None:
        stmt = stmt.limit(limit)
    return list(session.execute(stmt).scalars())


# -- bots ------------------------------------------------------------------

def create_bot(session: Session, **fields) -> Bot:
    bot = Bot(**fields)
    session.add(bot)
    session.flush()
    return bot


def get_bot(session: Session, bot_id: int) -> Optional[Bot]:
    return session.get(Bot, bot_id)


def get_bot_by_name(session: Session, name: str) -> Optional[Bot]:
    return session.execute(
        select(Bot).where(Bot.name == name)
    ).scalar_one_or_none()


def list_bots(session: Session, enabled_only: bool = False) -> list[Bot]:
    stmt = select(Bot).order_by(Bot.id)
    if enabled_only:
        # Matches the partial index on (enabled) where enabled is true.
        stmt = stmt.where(Bot.enabled.is_(True))
    return list(session.execute(stmt).scalars())


def update_bot(session: Session, bot: Bot, **changes) -> Bot:
    """Apply field changes to a bot.

    Only the fields a caller passes are touched, so tuning one parameter cannot
    blank out the rest of the record by omission.
    """
    for field, value in changes.items():
        if value is not None:
            setattr(bot, field, value)
    session.flush()
    return bot


def clone_bot(session: Session, bot: Bot, name: str, **overrides) -> Bot:
    """Copy a bot under a new name, disabled.

    Disabled regardless of the original's state: a clone exists to be retuned
    before it trades, and one that starts enabled would be trading the parent's
    parameters against the same account before anyone looked at it.
    """
    fields = {
        'strategy_id': bot.strategy_id,
        'parameters': dict(bot.parameters or {}),
        'symbols': list(bot.symbols or []),
        'timeframe': bot.timeframe,
        'capital_budget': bot.capital_budget,
        'risk_limits': dict(bot.risk_limits or {}),
        'mode': bot.mode,
    }
    fields.update({k: v for k, v in overrides.items() if v is not None})
    return create_bot(session, name=name, enabled=False, **fields)


def bot_open_positions(session: Session, bot_id: int) -> list:
    from db.models import PositionRow
    return list(session.execute(
        select(PositionRow).where(PositionRow.bot_id == bot_id)
    ).scalars())


# Event types only a running runner produces. Configuration changes are
# excluded on purpose: enabling a bot writes a `bot_updated` row, so counting
# every event would make the act of enabling a bot look like the bot running.
# That is the precise misreport this function exists to prevent.
RUNNER_EVENT_TYPES = (
    'signal', 'order_submitted', 'fill', 'order_rejected', 'tick_error',
    'reconciliation', 'session', 'forced_flatten', 'risk_decision',
    'live_blocked',
)


def last_activity_at(session: Session, bot_id: int) -> Optional[datetime]:
    """When a runner last did something for this bot.

    Answers "is a runner actually attached?". `enabled` records intent only -- a
    bot can be enabled with no process running anywhere -- so the UI needs a
    second, independent signal, and it has to come from work a runner does
    rather than from anything a person can click.
    """
    return session.execute(
        select(AuditLog.occurred_at)
        .where(
            AuditLog.bot_id == bot_id,
            AuditLog.event_type.in_(RUNNER_EVENT_TYPES),
        )
        .order_by(AuditLog.id.desc())
        .limit(1)
    ).scalar_one_or_none()


def blocked_order_counts(session: Session, bot_id: int) -> dict:
    """How many orders each rule has blocked for this bot.

    The operational question a risk gate raises is "what is it actually
    stopping?", and a count per rule answers it directly.
    """
    from sqlalchemy import func as sa_func
    from db.models import Order

    rows = session.execute(
        select(Order.blocked_by_rule, sa_func.count())
        .where(Order.bot_id == bot_id, Order.status == 'blocked')
        .group_by(Order.blocked_by_rule)
    ).all()
    return {rule: count for rule, count in rows if rule}


# -- kill switch -----------------------------------------------------------

def get_kill_switch(session: Session) -> KillSwitch:
    """Return the singleton row, creating it disengaged if absent.

    Never returns None. A missing row must not be readable as "not engaged by
    default" at a call site that is deciding whether to place an order.
    """
    switch = session.get(KillSwitch, 1)
    if switch is None:
        switch = KillSwitch(id=1, engaged=False)
        session.add(switch)
        session.flush()
    return switch


def set_kill_switch(
    session: Session, engaged: bool, reason: Optional[str] = None
) -> KillSwitch:
    switch = get_kill_switch(session)
    switch.engaged = engaged
    switch.reason = reason
    # The check constraint requires a time whenever engaged, so this is not
    # bookkeeping: a switch engaged with no timestamp will not insert.
    switch.engaged_at = datetime.now(timezone.utc) if engaged else None
    session.flush()
    return switch


# -- audit -----------------------------------------------------------------

def append_audit(
    session: Session,
    event_type: str,
    payload: dict,
    bot_id: Optional[int] = None,
    symbol: Optional[str] = None,
) -> AuditLog:
    """Append one audit row. Never updates, never deletes."""
    entry = AuditLog(
        event_type=event_type, payload=payload, bot_id=bot_id, symbol=symbol
    )
    session.add(entry)
    session.flush()
    return entry


def recent_audit(
    session: Session,
    limit: int = 100,
    bot_id: Optional[int] = None,
    event_type: Optional[str] = None,
) -> list[AuditLog]:
    stmt = select(AuditLog).order_by(AuditLog.id.desc()).limit(limit)
    if bot_id is not None:
        stmt = stmt.where(AuditLog.bot_id == bot_id)
    if event_type is not None:
        stmt = stmt.where(AuditLog.event_type == event_type)
    return list(session.execute(stmt).scalars())


# -- orders ----------------------------------------------------------------

def find_order_for_bar(
    session: Session, bot_id: int, symbol: str, bar_timestamp: datetime
) -> Optional[Order]:
    """The order this bot already placed for this symbol on this bar, if any.

    The read side of the idempotency guarantee. A runner that restarts and
    replays a bar checks here first, so a replay cannot become a second order.
    """
    return session.execute(
        select(Order).where(
            Order.bot_id == bot_id,
            Order.symbol == symbol,
            Order.bar_timestamp == bar_timestamp,
        )
    ).scalar_one_or_none()
