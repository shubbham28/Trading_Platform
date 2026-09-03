"""
Database schema.

Design notes worth knowing before changing anything here.

MONEY IS `numeric`, NEVER float. A float cannot represent 0.10 exactly, and an
accumulated rounding error in a P&L column is a number you cannot reconcile
against a broker statement. Prices and quantities use numeric(18,8) so fractional
shares and crypto fit; cash amounts use numeric(18,4).

TIMES ARE `timestamptz`. A naive timestamp is ambiguous the moment anything
crosses a timezone or a DST boundary, and market data is full of both.

IDS ARE `bigint identity`. Sequential, 8 bytes, no index fragmentation. A random
UUIDv4 primary key scatters inserts across the index, which matters on the tables
that grow fastest here (audit_log, equity points).

JSON COLUMNS map to `jsonb` on Postgres and to plain JSON text on SQLite, so the
tests can run without a Postgres server. jsonb is the real target; SQLite is a
convenience for the test suite.

EVERY FOREIGN KEY IS INDEXED. Postgres does not do this automatically, and an
unindexed FK makes both JOINs and ON DELETE CASCADE do full table scans.

IDENTIFIERS ARE LOWERCASE snake_case, unquoted. Mixed-case identifiers need
quoting forever and confuse tooling.
"""
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import (
    JSON, BigInteger, Boolean, CheckConstraint, Date, DateTime, ForeignKey,
    Identity, Index, Integer, Numeric, SmallInteger, Text, UniqueConstraint, func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# jsonb where it exists, JSON text on SQLite so tests need no server.
JsonB = JSON().with_variant(JSONB(), 'postgresql')

# Prices and share counts: 8 decimal places covers fractional shares and crypto.
PRICE = Numeric(18, 8)
# Cash amounts: 4 places is more than any venue reports and avoids float drift.
MONEY = Numeric(18, 4)
# Ratios stored as fractions (0.0734 = 7.34%).
RATIO = Numeric(12, 8)

# bigint, not int: `audit_log` and `backtest_equity_points` are the fast-growing
# tables here and int tops out at 2.1 billion. SQLite only auto-increments a
# column declared exactly INTEGER PRIMARY KEY, hence the variant.
BIGID = BigInteger().with_variant(Integer, 'sqlite')


def big_pk() -> Any:
    """A `bigint generated always as identity` primary key.

    `identity` rather than `serial`: it is the SQL standard, and unlike serial it
    does not leave an independently-owned sequence that can drift from the table.
    `always` blocks an explicit id on insert, which is the point -- a hand-set id
    is how a sequence ends up handing out a value that already exists.
    """
    return mapped_column(BIGID, Identity(always=True), primary_key=True)

MODES = ('paper', 'live')
ORDER_SIDES = ('buy', 'sell')
ORDER_TYPES = ('market', 'limit', 'stop', 'stop_limit')
ORDER_STATUSES = (
    'pending',      # created locally, not yet sent
    # A live order the risk gate allowed and that is waiting for a person. It is
    # not at the broker and may never be. Distinct from 'pending', which means
    # "about to be sent", because the difference decides whether anyone needs to
    # do something.
    'awaiting_approval',
    'submitted',    # accepted by the broker
    'partial',      # partially filled
    'filled',
    'cancelled',
    'rejected',     # broker said no
    'blocked',      # the risk gate said no; never reached the broker
    'expired',      # including an approval nobody acted on in time
)
POSITION_SIDES = ('long', 'short')


class Base(DeclarativeBase):
    pass


def _enum_check(column: str, allowed: tuple, name: str) -> CheckConstraint:
    """A text column constrained to a fixed set.

    Text plus a check constraint rather than a Postgres enum type: adding a value
    to an enum is a migration that cannot run inside a transaction on older
    Postgres, whereas editing a check constraint is ordinary DDL.
    """
    values = ', '.join(f"'{v}'" for v in allowed)
    return CheckConstraint(f"{column} in ({values})", name=name)


class Bot(Base):
    """A deployed strategy instance.

    This is the config record that makes a new bot a row rather than a code
    change: it names a strategy class from the registry and carries the
    parameters, symbols, budget and risk limits for this particular instance.
    """
    __tablename__ = 'bots'

    id: Mapped[int] = big_pk()
    name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Registry key from strategies/__init__.py, e.g. 'vwap_reversion'.
    strategy_id: Mapped[str] = mapped_column(Text, nullable=False)
    parameters: Mapped[dict] = mapped_column(JsonB, nullable=False, default=dict)
    # JSON rather than text[]: a Postgres array would not round-trip on SQLite,
    # and the test suite runs without a Postgres server.
    symbols: Mapped[list] = mapped_column(JsonB, nullable=False, default=list)
    timeframe: Mapped[str] = mapped_column(Text, nullable=False)

    capital_budget: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    risk_limits: Mapped[dict] = mapped_column(JsonB, nullable=False, default=dict)
    mode: Mapped[str] = mapped_column(Text, nullable=False, default='paper')

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
        onupdate=func.now(),
    )

    orders: Mapped[list['Order']] = relationship(back_populates='bot')
    positions: Mapped[list['PositionRow']] = relationship(
        back_populates='bot', cascade='all, delete-orphan'
    )

    __table_args__ = (
        _enum_check('mode', MODES, 'bots_mode_check'),
        CheckConstraint('capital_budget > 0', name='bots_capital_budget_positive'),
        # Enabled bots are read on every runner tick; disabled ones never are.
        # A partial index stays small no matter how many retired bots accumulate.
        Index('bots_enabled_idx', 'enabled', postgresql_where=text('enabled')),
    )


class Order(Base):
    """An order the system decided to place, whether or not it reached a broker.

    Blocked and rejected orders are rows here too. An order the risk gate refused
    is a fact worth keeping -- "why did nothing happen at 09:31?" is only
    answerable if the refusal was recorded.
    """
    __tablename__ = 'orders'

    id: Mapped[int] = big_pk()
    # Nullable: manual orders from the UI have no bot.
    bot_id: Mapped[Optional[int]] = mapped_column(
        BIGID, ForeignKey('bots.id', ondelete='SET NULL')
    )

    # The idempotency key sent to the broker. A retry after a network timeout
    # reuses it, so the broker deduplicates instead of double-filling.
    client_order_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    broker_order_id: Mapped[Optional[str]] = mapped_column(Text, unique=True)

    symbol: Mapped[str] = mapped_column(Text, nullable=False)
    side: Mapped[str] = mapped_column(Text, nullable=False)
    order_type: Mapped[str] = mapped_column(Text, nullable=False)
    qty: Mapped[Decimal] = mapped_column(PRICE, nullable=False)
    limit_price: Mapped[Optional[Decimal]] = mapped_column(PRICE)
    stop_price: Mapped[Optional[Decimal]] = mapped_column(PRICE)
    time_in_force: Mapped[str] = mapped_column(Text, nullable=False, default='day')

    status: Mapped[str] = mapped_column(Text, nullable=False, default='pending')
    mode: Mapped[str] = mapped_column(Text, nullable=False, default='paper')

    # The bar whose close produced this decision. Part of the idempotency
    # identity: one bot gets at most one order per symbol per bar, so a runner
    # restart that replays a bar cannot double-submit.
    bar_timestamp: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    # The strategy's own words for why, carried through so a fill can be traced
    # back to the reasoning that caused it.
    reason: Mapped[Optional[str]] = mapped_column(Text)
    # Which risk rule blocked this, when status is 'blocked'. Named, not a flag:
    # "an order was blocked" is not actionable, "max_daily_loss blocked it" is.
    blocked_by_rule: Mapped[Optional[str]] = mapped_column(Text)

    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    submitted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    # When a person was asked. An approval request has to carry its own age:
    # approving a signal from three hours ago is trading on information the
    # strategy would no longer act on, so requests expire rather than queue up.
    approval_requested_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    approval_note: Mapped[Optional[str]] = mapped_column(Text)

    bot: Mapped[Optional['Bot']] = relationship(back_populates='orders')
    fills: Mapped[list['Fill']] = relationship(
        back_populates='order', cascade='all, delete-orphan'
    )

    __table_args__ = (
        _enum_check('side', ORDER_SIDES, 'orders_side_check'),
        _enum_check('order_type', ORDER_TYPES, 'orders_type_check'),
        _enum_check('status', ORDER_STATUSES, 'orders_status_check'),
        _enum_check('mode', MODES, 'orders_mode_check'),
        CheckConstraint('qty > 0', name='orders_qty_positive'),
        CheckConstraint(
            "order_type not in ('limit', 'stop_limit') or limit_price is not null",
            name='orders_limit_price_required',
        ),
        CheckConstraint(
            "order_type not in ('stop', 'stop_limit') or stop_price is not null",
            name='orders_stop_price_required',
        ),
        CheckConstraint(
            "status <> 'blocked' or blocked_by_rule is not null",
            name='orders_blocked_needs_rule',
        ),
        CheckConstraint(
            "status <> 'awaiting_approval' or approval_requested_at is not null",
            name='orders_awaiting_needs_request_time',
        ),
        # The real idempotency guarantee: one order per bot, symbol and bar.
        # Partial so that manual orders (bot_id null) are unconstrained.
        Index(
            'orders_bot_symbol_bar_uniq', 'bot_id', 'symbol', 'bar_timestamp',
            unique=True,
            postgresql_where=text('bot_id is not null and bar_timestamp is not null'),
            sqlite_where=text('bot_id is not null and bar_timestamp is not null'),
        ),
        # Foreign key index: Postgres does not create one, and without it every
        # "orders for this bot" query and every cascade is a full scan.
        Index('orders_bot_id_idx', 'bot_id'),
        # Equality column first, range column last.
        Index('orders_symbol_requested_idx', 'symbol', 'requested_at'),
        Index('orders_status_requested_idx', 'status', 'requested_at'),
        # Reconciliation only ever looks at orders still in flight. An order
        # awaiting approval is deliberately absent: it is not at the broker, so
        # it cannot be a source of divergence.
        Index(
            'orders_open_idx', 'requested_at',
            postgresql_where=text("status in ('pending', 'submitted', 'partial')"),
        ),
        # The approval queue, read on every page load and by the expiry sweep.
        Index(
            'orders_awaiting_approval_idx', 'approval_requested_at',
            postgresql_where=text("status = 'awaiting_approval'"),
        ),
    )


class Fill(Base):
    """An execution against an order. One order may fill in several pieces."""
    __tablename__ = 'fills'

    id: Mapped[int] = big_pk()
    order_id: Mapped[int] = mapped_column(
        BIGID, ForeignKey('orders.id', ondelete='CASCADE'), nullable=False
    )
    broker_fill_id: Mapped[Optional[str]] = mapped_column(Text, unique=True)

    qty: Mapped[Decimal] = mapped_column(PRICE, nullable=False)
    price: Mapped[Decimal] = mapped_column(PRICE, nullable=False)
    commission: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=0)
    filled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    order: Mapped['Order'] = relationship(back_populates='fills')

    __table_args__ = (
        CheckConstraint('qty > 0', name='fills_qty_positive'),
        CheckConstraint('price > 0', name='fills_price_positive'),
        CheckConstraint('commission >= 0', name='fills_commission_non_negative'),
        Index('fills_order_id_idx', 'order_id'),
        Index('fills_filled_at_idx', 'filled_at'),
    )


class PositionRow(Base):
    """The system's belief about an open position.

    Named PositionRow so it cannot be confused with `strategies.base.Position`,
    which is the in-memory value a strategy reasons about. Reconciliation treats
    the broker as truth and corrects this table, never the reverse.
    """
    __tablename__ = 'positions'

    id: Mapped[int] = big_pk()
    bot_id: Mapped[int] = mapped_column(
        BIGID, ForeignKey('bots.id', ondelete='CASCADE'), nullable=False
    )
    symbol: Mapped[str] = mapped_column(Text, nullable=False)

    # Signed: positive long, negative short. A flat book is the absence of a row.
    qty: Mapped[Decimal] = mapped_column(PRICE, nullable=False)
    entry_price: Mapped[Decimal] = mapped_column(PRICE, nullable=False)
    entry_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
        onupdate=func.now(),
    )

    bot: Mapped['Bot'] = relationship(back_populates='positions')

    __table_args__ = (
        CheckConstraint('qty <> 0', name='positions_qty_nonzero'),
        CheckConstraint('entry_price > 0', name='positions_entry_price_positive'),
        UniqueConstraint('bot_id', 'symbol', name='positions_bot_symbol_uniq'),
        Index('positions_bot_id_idx', 'bot_id'),
    )


class EquitySnapshot(Base):
    """Account or per-bot equity at a point in time."""
    __tablename__ = 'equity_snapshots'

    id: Mapped[int] = big_pk()
    # Null means account level rather than attributable to one bot.
    bot_id: Mapped[Optional[int]] = mapped_column(
        BIGID, ForeignKey('bots.id', ondelete='CASCADE')
    )
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    equity: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    cash: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    drawdown: Mapped[Decimal] = mapped_column(RATIO, nullable=False, default=0)

    __table_args__ = (
        CheckConstraint('drawdown >= 0', name='equity_drawdown_non_negative'),
        Index('equity_bot_captured_idx', 'bot_id', 'captured_at'),
        Index('equity_captured_idx', 'captured_at'),
    )


class AuditLog(Base):
    """Append-only record of everything the system decided and did.

    Never updated, never deleted. When a live account behaves in a way nobody
    expected, this table is the only thing that can answer why, and a row that
    can be edited after the fact answers nothing.
    """
    __tablename__ = 'audit_log'

    id: Mapped[int] = big_pk()
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    bot_id: Mapped[Optional[int]] = mapped_column(
        BIGID, ForeignKey('bots.id', ondelete='SET NULL')
    )
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    symbol: Mapped[Optional[str]] = mapped_column(Text)
    # The inputs that produced the decision, not just its outcome. A logged
    # conclusion without its inputs cannot be re-derived or disputed.
    payload: Mapped[dict] = mapped_column(JsonB, nullable=False, default=dict)

    __table_args__ = (
        Index('audit_occurred_idx', 'occurred_at'),
        Index('audit_bot_occurred_idx', 'bot_id', 'occurred_at'),
        Index('audit_event_occurred_idx', 'event_type', 'occurred_at'),
    )


class KillSwitch(Base):
    """One row. When engaged, every bot flattens and stops.

    A single row rather than a config file or an env var, because it has to be
    changeable from the UI while the runner is mid-session and readable by the
    runner before every order without a restart.
    """
    __tablename__ = 'kill_switch'

    # autoincrement off: a singleton needs no sequence, and a sequence-supplied
    # default would hand out 2 on the next insert and collide with the id = 1
    # check constraint. The id is always literally 1.
    id: Mapped[int] = mapped_column(
        SmallInteger, primary_key=True, autoincrement=False, default=1
    )
    engaged: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    engaged_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    reason: Mapped[Optional[str]] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        CheckConstraint('id = 1', name='kill_switch_singleton'),
        CheckConstraint(
            'engaged = false or engaged_at is not null',
            name='kill_switch_engaged_needs_time',
        ),
    )


class LiveSettings(Base):
    """One row governing live trading. Separate from the kill switch on purpose.

    The kill switch is an emergency stop for everything. This is the standing
    posture for live orders specifically: whether they need a person, and how
    large one is allowed to be.

    `max_order_value` defaults to **zero**, which blocks every live order. That
    is the fail-closed default the plan asks for: live trading cannot begin by
    accident or by inheriting a paper configuration, only by someone deliberately
    setting a ceiling.
    """
    __tablename__ = 'live_settings'

    id: Mapped[int] = mapped_column(
        SmallInteger, primary_key=True, autoincrement=False, default=1
    )

    # When false, every live order waits for a person. Turning it on is the
    # "deliberate second action" from the plan, and it demands a written note.
    auto_approve: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    auto_approve_note: Mapped[Optional[str]] = mapped_column(Text)
    auto_approve_enabled_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )

    # Hard ceiling on a single live order's notional, independent of any bot's
    # own limits. A bot's limits were tuned against paper; this is the number the
    # operator stands behind for real money.
    max_order_value: Mapped[Decimal] = mapped_column(
        MONEY, nullable=False, default=0
    )

    # How long an approval request stays actionable. Past this it expires
    # unapproved, because the bar that produced it is long gone.
    approval_timeout_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, default=300
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        CheckConstraint('id = 1', name='live_settings_singleton'),
        CheckConstraint('max_order_value >= 0', name='live_settings_ceiling_non_negative'),
        CheckConstraint(
            'approval_timeout_seconds > 0',
            name='live_settings_timeout_positive',
        ),
        # Turning auto-approve on without saying why leaves nothing to review
        # later, and this is the single most consequential setting here.
        CheckConstraint(
            'auto_approve = false or '
            '(auto_approve_note is not null and auto_approve_enabled_at is not null)',
            name='live_settings_auto_approve_needs_note',
        ),
    )


class BacktestRun(Base):
    """A stored backtest result.

    `config` is not decoration: it records the commission, slippage, sizing and
    short policy the numbers were produced under. A Sharpe ratio without its cost
    assumptions is not a result, and two runs of the same strategy are only
    comparable if you can see what each one assumed.
    """
    __tablename__ = 'backtest_runs'

    id: Mapped[int] = big_pk()
    strategy_id: Mapped[str] = mapped_column(Text, nullable=False)
    symbol: Mapped[str] = mapped_column(Text, nullable=False)
    timeframe: Mapped[str] = mapped_column(Text, nullable=False)
    start_date: Mapped[Any] = mapped_column(Date, nullable=False)
    end_date: Mapped[Any] = mapped_column(Date, nullable=False)

    parameters: Mapped[dict] = mapped_column(JsonB, nullable=False, default=dict)
    config: Mapped[dict] = mapped_column(JsonB, nullable=False, default=dict)
    metrics: Mapped[dict] = mapped_column(JsonB, nullable=False, default=dict)
    # The engine's ExecutionAudit: unfilled intents, rejections, forced
    # liquidations, sessions at risk of an unhandled early close.
    audit: Mapped[dict] = mapped_column(JsonB, nullable=False, default=dict)
    # Trades are tens to hundreds per run, so jsonb is the right shape. The
    # equity curve is not -- see BacktestEquityPoint.
    trades: Mapped[list] = mapped_column(JsonB, nullable=False, default=list)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    equity_points: Mapped[list['BacktestEquityPoint']] = relationship(
        back_populates='run', cascade='all, delete-orphan',
        order_by='BacktestEquityPoint.bar_index',
    )

    __table_args__ = (
        CheckConstraint('end_date >= start_date', name='backtest_dates_ordered'),
        Index('backtest_strategy_created_idx', 'strategy_id', 'created_at'),
        Index('backtest_symbol_created_idx', 'symbol', 'created_at'),
    )


class BacktestEquityPoint(Base):
    """One point of a run's equity curve.

    Its own table rather than a jsonb array on the run. A year of one-minute bars
    is roughly 98,000 points; as a single jsonb value that is a multi-megabyte
    blob that has to be read and rewritten whole, and cannot be queried,
    downsampled, or paged. Rows can be. They are bulk-inserted in one statement
    per run, not one round trip per point.
    """
    __tablename__ = 'backtest_equity_points'

    id: Mapped[int] = big_pk()
    run_id: Mapped[int] = mapped_column(
        BIGID, ForeignKey('backtest_runs.id', ondelete='CASCADE'), nullable=False
    )
    bar_index: Mapped[int] = mapped_column(Integer, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    equity: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    drawdown: Mapped[Decimal] = mapped_column(RATIO, nullable=False, default=0)

    run: Mapped['BacktestRun'] = relationship(back_populates='equity_points')

    __table_args__ = (
        UniqueConstraint('run_id', 'bar_index', name='backtest_equity_run_bar_uniq'),
        Index('backtest_equity_run_idx', 'run_id', 'bar_index'),
    )
