"""
The bot runner.

One tick, in order:

  1. Kill switch. Checked every tick, not only before an order, so an engaged
     switch stops a bot that is about to decide rather than one that already has.
  2. Replay guard. If this bar already produced an order, skip it. A restart that
     re-reads the last bar must not act on it twice.
  3. Load the position from the database. The runner never keeps it in memory
     between ticks -- the same reason strategies do not: two copies drift.
  4. Prepare indicators and ask the strategy, through the exact path the
     backtester uses.
  5. Audit the signal. Every bar, including holds, because "the audit log
     accounts for every bar" is the Phase 4 exit criterion and a log that only
     records actions cannot tell a quiet bot from a stopped one.
  6. Flat-by-close backstop.
  7. Risk gate, then router.
  8. Snapshot bot equity, because the daily-loss rules are measured against
     snapshots and are only as fresh as the last one.

THE LOAD-BEARING PROPERTY. Steps 3, 4 and 7 are the same calls the backtester
makes, in the same order, against the same objects. That is what makes a backtest
number mean anything, and `test_runner_matches_backtester` fails if it stops
being true.

SUPERVISION. A tick that raises is caught, audited, and counted. One bad bar must
not end a session, and a bot failing every bar must not keep trying: after
`max_consecutive_errors` it is disabled, which persists across a restart.

Synchronous by choice. The plan said async; nothing at one-minute cadence is
I/O-bound enough to need concurrency, and a sync loop is deterministically
testable. Recorded in TODOS.md as a deviation rather than left implicit.
"""
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

import pandas as pd

from app.session import build_contexts
from brokers.base import BrokerAdapter
from db import repository
from db.models import Bot
from indicators import calculate_all_indicators
from risk.context import (
    build_context, evaluate_and_record, record_start_of_day_equity,
)
from risk.contracts import BotRiskLimits, OrderIntent
from risk.gate import RiskGate
from runner.clock import BarClock, BarEvent
from runner.reconcile import reconcile
from runner.router import OrderRouter
from strategies import get_strategy
from strategies.base import Position

logger = logging.getLogger(__name__)

AUDIT_SIGNAL = 'signal'
AUDIT_TICK_ERROR = 'tick_error'
AUDIT_FORCED_FLATTEN = 'forced_flatten'
AUDIT_SHORT_BLOCKED = 'short_blocked'
AUDIT_SESSION = 'session'


@dataclass
class TickResult:
    """What happened on one bar. Returned so a caller can assert on it."""
    timestamp: pd.Timestamp
    action: str = 'hold'
    reason: str = ''
    skipped: Optional[str] = None
    blocked_by_rule: Optional[str] = None
    order_id: Optional[int] = None
    error: Optional[str] = None


@dataclass
class SessionResult:
    ticks: list = field(default_factory=list)
    halted: bool = False
    halt_reason: Optional[str] = None

    @property
    def bars_seen(self) -> int:
        return len(self.ticks)

    @property
    def orders_placed(self) -> int:
        """Orders that actually reached the broker.

        A blocked order is written to `orders` too and so has an id, but nothing
        was placed. Counting those here reported "orders=2" for a session where
        the gate refused both and the book never moved.
        """
        return sum(
            1 for t in self.ticks
            if t.order_id is not None and t.blocked_by_rule is None
        )

    @property
    def orders_blocked(self) -> int:
        return sum(1 for t in self.ticks if t.blocked_by_rule is not None)

    @property
    def errors(self) -> int:
        return sum(1 for t in self.ticks if t.error is not None)


class BotRunner:
    """Drives one bot over one symbol's bars."""

    def __init__(
        self,
        session_factory,
        broker: BrokerAdapter,
        bot_id: int,
        gate: Optional[RiskGate] = None,
        router: Optional[OrderRouter] = None,
        max_consecutive_errors: int = 3,
        reconcile_interval_seconds: float = 60.0,
        clock_now=None,
    ):
        # A factory rather than a session: each tick gets its own transaction, so
        # one bar's failure cannot roll back the previous bar's recorded order.
        self.session_factory = session_factory
        self.broker = broker
        self.bot_id = bot_id
        self.router = router or OrderRouter(broker)
        self._gate = gate
        self.max_consecutive_errors = max_consecutive_errors
        # Reconciled at startup and then on this interval, per the plan. Drift
        # discovered at the next restart is drift the bot traded through for
        # however long the session lasted.
        self.reconcile_interval_seconds = reconcile_interval_seconds
        self._now = clock_now or (lambda: datetime.now(timezone.utc))
        self._last_reconciled: Optional[datetime] = None
        self._consecutive_errors = 0

    # -- session lifecycle -------------------------------------------------

    def start_session(self, session) -> None:
        """Record the baselines the daily-loss rules need, then reconcile.

        Without a start-of-day snapshot the daily-loss rules block every opening
        order -- deliberately, since a missing baseline means the loss is
        unknown. So this is not optional setup, it is the thing that makes the
        bot able to trade at all.
        """
        bot = self._load_bot(session)
        account = self.broker.get_account()

        if repository is not None:
            record_start_of_day_equity(
                session, equity=account.equity, cash=account.cash
            )
            # A bot's equity baseline is its budget: at session open nothing is
            # committed, so the budget is what it has to work with.
            record_start_of_day_equity(
                session, equity=bot.capital_budget, cash=bot.capital_budget,
                bot_id=bot.id,
            )

        repository.append_audit(
            session, event_type=AUDIT_SESSION,
            payload={'event': 'started', 'account_equity': str(account.equity),
                     'bot_budget': str(bot.capital_budget)},
            bot_id=bot.id,
        )

        result = reconcile(session, self.broker)
        if not result.in_sync:
            raise RuntimeError(
                f'refusing to start with local state out of step with the '
                f'broker: {result.describe()}'
            )

    def run_session(self, clock: BarClock) -> SessionResult:
        """Run until the clock stops, or the bot is halted."""
        result = SessionResult()

        with self.session_factory() as session:
            try:
                self.start_session(session)
                session.commit()
            except Exception as exc:
                session.rollback()
                result.halted = True
                result.halt_reason = str(exc)
                return result

        self._last_reconciled = self._now()

        for event in clock.ticks():
            divergence = self._periodic_reconcile()
            if divergence is not None:
                result.halted = True
                result.halt_reason = divergence
                break

            tick = self.tick(event)
            result.ticks.append(tick)

            if tick.error is None:
                self._consecutive_errors = 0
            else:
                self._consecutive_errors += 1
                if self._consecutive_errors >= self.max_consecutive_errors:
                    result.halted = True
                    result.halt_reason = (
                        f'{self._consecutive_errors} consecutive tick failures; '
                        f'last: {tick.error}'
                    )
                    self._disable_bot(result.halt_reason)
                    break

            if tick.skipped == 'bot disabled':
                result.halted = True
                result.halt_reason = 'bot disabled'
                break

        return result

    def _periodic_reconcile(self) -> Optional[str]:
        """Re-check against the broker if the interval has elapsed.

        Returns a halt reason on divergence, None otherwise. Mid-session rather
        than only at startup, because drift found at the next restart is drift
        the bot traded through for the rest of the session.
        """
        if self.reconcile_interval_seconds is None:
            return None

        now = self._now()
        if self._last_reconciled is not None:
            elapsed = (now - self._last_reconciled).total_seconds()
            if elapsed < self.reconcile_interval_seconds:
                return None

        self._last_reconciled = now
        try:
            with self.session_factory() as session:
                outcome = reconcile(session, self.broker)
                session.commit()
        except Exception as exc:
            logger.exception('reconciliation failed')
            return f'reconciliation failed: {exc}'

        if outcome.in_sync:
            return None
        return (
            f'position diverged from the broker mid-session: '
            f'{outcome.describe()}'
        )

    # -- one bar -----------------------------------------------------------

    def tick(self, event: BarEvent) -> TickResult:
        """Process one completed bar.

        Every failure mode returns a TickResult rather than raising, so the
        supervisor above can count it and decide. A tick that raised out of here
        would take the session with it.
        """
        try:
            with self.session_factory() as session:
                try:
                    outcome = self._tick(session, event)
                    session.commit()
                    return outcome
                except Exception:
                    session.rollback()
                    raise
        except Exception as exc:
            logger.exception('tick failed at %s', event.timestamp)
            self._audit_tick_error(event, exc)
            return TickResult(
                timestamp=event.timestamp, error=f'{type(exc).__name__}: {exc}'
            )

    def _tick(self, session, event: BarEvent) -> TickResult:
        bot = self._load_bot(session)

        if not bot.enabled:
            return TickResult(
                timestamp=event.timestamp, skipped='bot disabled'
            )

        # 1. Kill switch, every tick.
        switch = repository.get_kill_switch(session)

        # 2. Replay guard. Checked before anything else costly, and before the
        #    unique index on (bot, symbol, bar) would raise instead.
        already = repository.find_order_for_bar(
            session, bot.id, event.symbol, event.timestamp.to_pydatetime()
        )
        if already is not None:
            return TickResult(
                timestamp=event.timestamp,
                skipped=f'bar already handled (order {already.id})',
            )

        # 3. Position from the database, never from memory.
        position = self._load_position(session, bot.id, event.symbol)

        # 4. The backtester's exact path.
        strategy = get_strategy(bot.strategy_id, bot.parameters)
        prepared = strategy.prepare(calculate_all_indicators(event.bars))
        contexts = build_contexts(prepared, bot.timeframe)
        ctx = contexts[-1]

        if len(prepared) <= strategy.warmup_bars():
            repository.append_audit(
                session, event_type=AUDIT_SIGNAL,
                payload={'action': 'hold', 'reason': 'warming up',
                         'bar': event.timestamp.isoformat(),
                         'bars_seen': len(prepared),
                         'warmup_bars': strategy.warmup_bars()},
                bot_id=bot.id, symbol=event.symbol,
            )
            return TickResult(
                timestamp=event.timestamp, action='hold', reason='warming up'
            )

        signal = strategy.analyze(prepared, ctx, position)

        # 5. Audit every bar, hold included.
        repository.append_audit(
            session, event_type=AUDIT_SIGNAL,
            payload={
                'action': signal.action, 'reason': signal.reason,
                'confidence': signal.confidence,
                'bar': event.timestamp.isoformat(),
                'close': float(prepared.iloc[-1]['close']),
                'position_qty': str(position.qty) if position else '0',
                'is_session_last_bar': ctx.is_session_last_bar,
                'kill_switch_engaged': switch.engaged,
            },
            bot_id=bot.id, symbol=event.symbol,
        )

        action, reason = signal.action, signal.reason

        # 6. Flat-by-close backstop. The strategies flatten themselves via
        #    BarContext, but a strategy that forgets to must not leave a bot
        #    holding overnight when its configuration says otherwise.
        limits = BotRiskLimits.from_bot(bot)
        if (
            limits.flat_by_close and ctx.is_session_last_bar
            and position is not None and action == 'hold'
        ):
            action = 'sell' if position.is_long else 'buy'
            reason = 'flat_by_close: runner flattened a position the strategy left open'
            repository.append_audit(
                session, event_type=AUDIT_FORCED_FLATTEN,
                payload={'position_qty': str(position.qty), 'reason': reason,
                         'bar': event.timestamp.isoformat()},
                bot_id=bot.id, symbol=event.symbol,
            )

        if action == 'hold':
            return TickResult(
                timestamp=event.timestamp, action='hold', reason=reason
            )

        # Shorts, gated where the backtester gates its own. Without this the
        # backtester refused a sell-while-flat (counting it in
        # intents_rejected_shorts_disabled) while the runner opened a short from
        # the identical signal -- backtest and live diverging on execution even
        # though the strategy core agreed.
        opening_short = position is None and action == 'sell'
        if opening_short and not limits.allow_short:
            repository.append_audit(
                session, event_type=AUDIT_SHORT_BLOCKED,
                payload={
                    'reason': (
                        'sell with no position would open a short, and '
                        'allow_short is off for this bot'
                    ),
                    'bar': event.timestamp.isoformat(),
                    'signal_reason': reason,
                },
                bot_id=bot.id, symbol=event.symbol,
            )
            return TickResult(
                timestamp=event.timestamp, action=action, reason=reason,
                skipped='shorts disabled for this bot',
            )

        # 7. Risk gate, then router.
        qty = self._order_quantity(bot, limits, position, action, prepared)
        if qty <= 0:
            return TickResult(
                timestamp=event.timestamp, action=action,
                reason='sized to zero shares', skipped='zero quantity',
            )

        intent = OrderIntent(
            bot_id=bot.id, symbol=event.symbol, side=action, qty=qty,
            estimated_price=Decimal(str(prepared.iloc[-1]['close'])),
            reason=reason, order_type='market',
            bar_timestamp=event.timestamp.to_pydatetime(), mode=bot.mode,
        )

        risk_context = build_context(session, self.broker, bot, event.symbol)
        decision, blocked_order = evaluate_and_record(
            session, self._gate_for(bot, limits), intent, risk_context
        )

        if decision.blocked:
            return TickResult(
                timestamp=event.timestamp, action=action, reason=reason,
                blocked_by_rule=decision.rule,
                order_id=blocked_order.id if blocked_order else None,
            )

        order, refusal = self.router.submit(session, intent)

        # 8. Snapshot, so the daily-loss rules have something fresh to read.
        self._snapshot_bot_equity(session, bot, event.symbol)

        return TickResult(
            timestamp=event.timestamp, action=action, reason=reason,
            order_id=order.id if order else None, skipped=refusal,
        )

    # -- helpers -----------------------------------------------------------

    def _gate_for(self, bot: Bot, limits: BotRiskLimits) -> RiskGate:
        if self._gate is not None:
            return self._gate
        from risk.contracts import AccountRiskLimits
        return RiskGate(AccountRiskLimits.from_env(), limits)

    def _order_quantity(
        self, bot: Bot, limits: BotRiskLimits, position, action: str, prepared
    ) -> Decimal:
        """How many shares to trade.

        Closing an existing position trades exactly that position -- a close that
        guesses its own size leaves a remainder nobody asked for. Opening sizes
        from the bot's budget and `max_position_pct`; the risk gate then has the
        final say, so this is a proposal rather than an authority.
        """
        price = Decimal(str(prepared.iloc[-1]['close']))
        if price <= 0:
            return Decimal('0')

        if position is not None:
            closing = (
                (position.is_long and action == 'sell')
                or (position.is_short and action == 'buy')
            )
            if closing:
                return abs(position.qty)

        budget = bot.capital_budget * Decimal(str(limits.max_position_pct)) / Decimal('100')
        return Decimal(int(budget / price))

    def _load_bot(self, session) -> Bot:
        bot = repository.get_bot(session, self.bot_id)
        if bot is None:
            raise LookupError(f'bot {self.bot_id} does not exist')
        return bot

    def _load_position(self, session, bot_id: int, symbol: str):
        from sqlalchemy import select
        from db.models import PositionRow

        row = session.execute(
            select(PositionRow).where(
                PositionRow.bot_id == bot_id, PositionRow.symbol == symbol
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        return Position(
            qty=int(row.qty), entry_price=float(row.entry_price),
            entry_time=row.entry_time,
        )

    def _snapshot_bot_equity(self, session, bot: Bot, symbol: str) -> None:
        """Record the bot's equity so its daily-loss limit stays current.

        Uncommitted budget plus the marked value of what it holds. Marked at the
        broker's prices, which is the only source of current value here.
        """
        from sqlalchemy import select
        from db.models import PositionRow

        rows = list(session.execute(
            select(PositionRow).where(PositionRow.bot_id == bot.id)
        ).scalars())

        marks = {p.symbol: p for p in self.broker.get_positions()}
        held_value = Decimal('0')
        cost_basis = Decimal('0')
        for row in rows:
            cost_basis += abs(row.qty) * row.entry_price
            mark = marks.get(row.symbol)
            if mark is not None and mark.qty != 0:
                # Value this bot's slice at the broker's average mark.
                per_share = abs(mark.market_value) / abs(mark.qty)
                held_value += abs(row.qty) * per_share
            else:
                held_value += abs(row.qty) * row.entry_price

        equity = bot.capital_budget - cost_basis + held_value
        snapshot_cash = bot.capital_budget - cost_basis

        from db.models import EquitySnapshot
        session.add(EquitySnapshot(
            bot_id=bot.id, captured_at=datetime.now(timezone.utc),
            equity=equity, cash=snapshot_cash, drawdown=Decimal('0'),
        ))
        session.flush()

    def _disable_bot(self, reason: str) -> None:
        with self.session_factory() as session:
            bot = repository.get_bot(session, self.bot_id)
            if bot is not None and bot.enabled:
                bot.enabled = False
                repository.append_audit(
                    session, event_type='bot_halted',
                    payload={'reason': reason}, bot_id=bot.id,
                )
            session.commit()

    def _audit_tick_error(self, event: BarEvent, exc: Exception) -> None:
        """Record a failed tick in its own transaction.

        Its own, because the tick's transaction has been rolled back -- writing
        the error into that transaction would roll the error back too, and the
        failure would leave no trace at all.
        """
        try:
            with self.session_factory() as session:
                repository.append_audit(
                    session, event_type=AUDIT_TICK_ERROR,
                    payload={'bar': event.timestamp.isoformat(),
                             'error': f'{type(exc).__name__}: {exc}'},
                    bot_id=self.bot_id, symbol=event.symbol,
                )
                session.commit()
        except Exception:
            logger.exception('could not record tick error')
