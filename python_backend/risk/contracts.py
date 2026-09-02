"""
Risk gate contracts.

The gate is a pure function of (intent, context) -> decision. Nothing in it
reads a database or calls a broker. That is deliberate: a risk rule that can only
be exercised against live state will not be exercised, and these are the ten
rules standing between a strategy bug and real money. Assembling the context is
a separate job (risk/context.py) with its own tests.
"""
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field


def _dec(value) -> Decimal:
    """Coerce to Decimal via str, never via float.

    Decimal(0.1) carries the float's representation error. Every number in this
    module is compared against a money limit, so that error is not academic.
    """
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


@dataclass(frozen=True)
class OrderIntent:
    """An order the system wants to place, before the gate has ruled on it."""
    bot_id: Optional[int]
    symbol: str
    side: str                    # 'buy' | 'sell'
    qty: Decimal
    # Best estimate of the fill price, used to value the order. The gate cannot
    # know the real fill, so every limit it enforces is approximate by nature --
    # which is why the limits should be set with headroom.
    estimated_price: Decimal
    reason: str = ''
    order_type: str = 'market'
    bar_timestamp: Optional[datetime] = None
    mode: str = 'paper'

    @property
    def notional(self) -> Decimal:
        return _dec(self.qty) * _dec(self.estimated_price)

    @property
    def signed_qty(self) -> Decimal:
        """Positive for a buy, negative for a sell."""
        return _dec(self.qty) if self.side == 'buy' else -_dec(self.qty)


@dataclass(frozen=True)
class RiskContext:
    """A snapshot of everything the gate is allowed to consider.

    Frozen, and assembled once per decision. A gate that re-reads live state
    mid-evaluation could allow an order under one set of numbers and log another,
    which makes the audit trail a work of fiction.
    """
    # -- account tier
    kill_switch_engaged: bool = False
    kill_switch_reason: Optional[str] = None
    account_equity: Decimal = Decimal('0')
    account_exposure: Decimal = Decimal('0')      # sum of |market value|
    account_open_positions: int = 0
    # Today's P&L, realised and unrealised, against the start-of-day baseline.
    # None means it could not be determined -- which is not the same as zero and
    # must never be treated as zero. See gate.py.
    account_daily_pnl: Optional[Decimal] = None

    # -- live gating (account tier)
    # False means every live order waits for a person. The gate does not do the
    # waiting -- the router does -- but the ceiling below is a hard cap that
    # applies whether or not a person would have approved it.
    live_auto_approved: bool = False
    # Ceiling on a single live order's notional. Zero blocks every live order,
    # which is the fail-closed default: live trading cannot begin by inheriting
    # a paper configuration, only by someone deliberately setting a number.
    live_max_order_value: Decimal = Decimal('0')

    # -- bot tier
    bot_budget: Decimal = Decimal('0')
    bot_exposure: Decimal = Decimal('0')
    bot_open_positions: int = 0
    bot_daily_pnl: Optional[Decimal] = None

    # -- position tier
    # This bot's existing position in the intent's symbol. Signed; 0 is flat.
    existing_position_qty: Decimal = Decimal('0')
    # Other bots already holding this symbol. Two bots independently sizing a
    # position in the same name produces double the intended exposure without
    # either one misbehaving.
    other_bots_holding_symbol: tuple = ()


class AccountRiskLimits(BaseModel):
    """Account-wide ceilings, applied to every bot's orders together.

    Read from the environment rather than the database. There is one account and
    one operator; a table for it would be a migration and a UI with no second
    user to serve. Phase 5 should move it into the database once there is a
    settings screen to edit it from -- noted in TODOS.md.
    """
    # Total exposure as a percentage of account equity. Over 100 means margin.
    max_total_exposure_pct: float = Field(default=100.0, gt=0)
    # Daily loss as a percentage of the start-of-day equity baseline.
    max_daily_loss_pct: float = Field(default=5.0, gt=0)
    max_open_positions: int = Field(default=10, gt=0)

    @classmethod
    def from_env(cls, env: Optional[dict] = None) -> 'AccountRiskLimits':
        import os
        source = env if env is not None else os.environ
        values = {}
        for name, key in (
            ('max_total_exposure_pct', 'RISK_MAX_TOTAL_EXPOSURE_PCT'),
            ('max_daily_loss_pct', 'RISK_MAX_DAILY_LOSS_PCT'),
            ('max_open_positions', 'RISK_MAX_OPEN_POSITIONS'),
        ):
            raw = source.get(key)
            if raw is not None and raw != '':
                values[name] = raw
        return cls(**values)


class BotRiskLimits(BaseModel):
    """Per-bot limits. Stored in `bots.risk_limits` as jsonb.

    Field names match the bot config record in the plan exactly, so a stored
    record and this model cannot drift into meaning different things.
    """
    # Largest position, as a percentage of this bot's capital budget.
    max_position_pct: float = Field(default=100.0, gt=0)
    # Absolute dollars. A bot that loses this much today stops opening.
    max_daily_loss: Decimal = Field(default=Decimal('1000000'), gt=0)
    max_open_positions: int = Field(default=5, gt=0)
    # Largest single order by notional value. Catches a fat-finger or a sizing
    # bug that the percentage limits would let through on a large budget.
    max_order_value: Decimal = Field(default=Decimal('1000000'), gt=0)
    # Enforced by the strategy via BarContext.is_session_last_bar, and backed up
    # by the runner. Not by the gate -- a rule that silently does nothing is
    # worse than no rule.
    flat_by_close: bool = True
    # Whether a 'sell' with no position may open a short. Default False, matching
    # BacktestConfig.allow_short, and that matching is the whole point: without
    # this field the backtester refused shorts while the live runner opened them
    # from the same signals, so backtest and live were once again different
    # algorithms. Enforced by the runner, where the backtester enforces its own.
    allow_short: bool = False

    @classmethod
    def from_bot(cls, bot) -> 'BotRiskLimits':
        """Build limits from a Bot row, falling back to defaults per field."""
        return cls(**(bot.risk_limits or {}))


@dataclass(frozen=True)
class RiskDecision:
    """The gate's ruling.

    `rule` is the name of the single rule that blocked the order. Named, not a
    boolean: "an order was blocked" is not actionable, "bot_max_daily_loss
    blocked it, bot is down 412.50 against a 400.00 limit" is.
    """
    allowed: bool
    rule: Optional[str] = None
    tier: Optional[str] = None
    detail: Optional[str] = None
    # True when the order reduces or closes an existing position, in which case
    # the gate does not apply exposure limits at all.
    is_reducing: bool = False

    @property
    def blocked(self) -> bool:
        return not self.allowed

    def as_payload(self, intent: OrderIntent, context: RiskContext) -> dict:
        """The audit payload: the ruling plus the inputs that produced it.

        Both halves matter. A logged conclusion without its inputs cannot be
        re-derived or disputed six weeks later when the question is why a bot
        did nothing all afternoon.
        """
        return {
            'allowed': self.allowed,
            'rule': self.rule,
            'tier': self.tier,
            'detail': self.detail,
            'is_reducing': self.is_reducing,
            'intent': {
                'bot_id': intent.bot_id,
                'symbol': intent.symbol,
                'side': intent.side,
                'qty': str(intent.qty),
                'estimated_price': str(intent.estimated_price),
                'notional': str(intent.notional),
                'order_type': intent.order_type,
                'mode': intent.mode,
                'reason': intent.reason,
                'bar_timestamp': (
                    intent.bar_timestamp.isoformat()
                    if intent.bar_timestamp else None
                ),
            },
            'context': {
                'kill_switch_engaged': context.kill_switch_engaged,
                'live_auto_approved': context.live_auto_approved,
                'live_max_order_value': str(context.live_max_order_value),
                'account_equity': str(context.account_equity),
                'account_exposure': str(context.account_exposure),
                'account_open_positions': context.account_open_positions,
                'account_daily_pnl': (
                    str(context.account_daily_pnl)
                    if context.account_daily_pnl is not None else None
                ),
                'bot_budget': str(context.bot_budget),
                'bot_exposure': str(context.bot_exposure),
                'bot_open_positions': context.bot_open_positions,
                'bot_daily_pnl': (
                    str(context.bot_daily_pnl)
                    if context.bot_daily_pnl is not None else None
                ),
                'existing_position_qty': str(context.existing_position_qty),
                'other_bots_holding_symbol': list(
                    context.other_bots_holding_symbol
                ),
            },
        }
