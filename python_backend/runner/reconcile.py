"""
Reconciliation.

The broker is where the money actually is. Local state is a belief about it, and
beliefs drift: a fill arrives while the process is restarting, someone closes a
position by hand in the Alpaca web UI, a network blip loses an acknowledgement.

WHAT A DIVERGENCE DOES, AND WHY IT IS NOT SILENTLY REPAIRED.

The plan says local state is reconciled to the broker and that a divergence
"raises and halts the bot". Those pull in opposite directions if taken literally
together, so this module takes the safer reading: detect, record, and halt.
It does not quietly adopt the broker's numbers.

Auto-adopting would mean a bot that has lost track of a position carries on with
corrected figures and the reason for the drift -- a missed fill, a manual trade,
a bug in fill handling -- goes uninvestigated. The one thing worse than a system
that knows it is confused is one that stops noticing.

`adopt_broker_state` exists for the operator to call once they know why. Recovery
is a deliberate act, not a default.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from brokers.base import BrokerAdapter
from db.models import Bot, PositionRow
from db.repository import append_audit

AUDIT_RECONCILIATION = 'reconciliation'
AUDIT_BOT_HALTED = 'bot_halted'


def qty_str(value: Decimal) -> str:
    """Format a quantity the same way regardless of where it came from.

    A `numeric(18,8)` column returns Decimal('10.00000000') while a broker
    returns Decimal('10'), so the naive str() of each differs and two audit rows
    describing the same book look like a disagreement. `normalize` strips the
    trailing zeros and the 'f' format stops it reaching for scientific notation
    on round numbers -- Decimal('10').normalize() is otherwise '1E+1'.
    """
    return format(Decimal(value).normalize(), 'f')


@dataclass(frozen=True)
class Divergence:
    """One symbol where our belief and the broker disagree."""
    symbol: str
    broker_qty: Decimal
    local_qty: Decimal
    # Which bots hold this symbol locally. Empty when only the broker has it,
    # which usually means a manual trade or a fill we never recorded.
    bot_ids: tuple = ()

    @property
    def difference(self) -> Decimal:
        return self.broker_qty - self.local_qty

    def describe(self) -> str:
        return (
            f'{self.symbol}: broker says {qty_str(self.broker_qty)}, we think '
            f'{qty_str(self.local_qty)} (difference {qty_str(self.difference)})'
        )


@dataclass
class ReconciliationResult:
    in_sync: bool
    divergences: list = field(default_factory=list)
    halted_bot_ids: list = field(default_factory=list)

    def describe(self) -> str:
        if self.in_sync:
            return 'local positions match the broker'
        return '; '.join(d.describe() for d in self.divergences)


def reconcile(
    session: Session,
    broker: BrokerAdapter,
    halt_on_divergence: bool = True,
) -> ReconciliationResult:
    """Compare local positions against the broker's, per symbol.

    Compared per symbol rather than per bot, because the broker has never heard
    of bots: two bots holding AAPL appear to it as one position. So the check is
    that our per-bot rows *sum* to what the broker reports.
    """
    broker_by_symbol = {
        p.symbol: p.qty for p in broker.get_positions() if p.qty != 0
    }

    local_rows = list(session.execute(select(PositionRow)).scalars())
    local_by_symbol: dict = {}
    bots_by_symbol: dict = {}
    for row in local_rows:
        local_by_symbol[row.symbol] = (
            local_by_symbol.get(row.symbol, Decimal('0')) + row.qty
        )
        bots_by_symbol.setdefault(row.symbol, []).append(row.bot_id)

    divergences = []
    for symbol in sorted(set(broker_by_symbol) | set(local_by_symbol)):
        broker_qty = broker_by_symbol.get(symbol, Decimal('0'))
        local_qty = local_by_symbol.get(symbol, Decimal('0'))
        if broker_qty != local_qty:
            divergences.append(Divergence(
                symbol=symbol, broker_qty=broker_qty, local_qty=local_qty,
                bot_ids=tuple(sorted(bots_by_symbol.get(symbol, []))),
            ))

    result = ReconciliationResult(
        in_sync=not divergences, divergences=divergences
    )

    append_audit(
        session, event_type=AUDIT_RECONCILIATION,
        payload={
            'in_sync': result.in_sync,
            'broker_positions': {
                s: qty_str(q) for s, q in broker_by_symbol.items()
            },
            'local_positions': {
                s: qty_str(q) for s, q in local_by_symbol.items()
            },
            'divergences': [
                {
                    'symbol': d.symbol, 'broker_qty': qty_str(d.broker_qty),
                    'local_qty': qty_str(d.local_qty),
                    'difference': qty_str(d.difference),
                    'bot_ids': list(d.bot_ids),
                }
                for d in divergences
            ],
        },
    )

    if divergences and halt_on_divergence:
        result.halted_bot_ids = halt_bots_for(session, divergences)

    return result


def halt_bots_for(session: Session, divergences: list) -> list:
    """Disable every bot implicated in a divergence.

    Disabling rather than deleting or pausing in memory: `bots.enabled` is what
    the runner reads, it survives a restart, and it is visible. A bot halted only
    in a process that then restarts is not halted.

    A divergence in a symbol no bot holds locally halts nothing here -- there is
    no bot to blame -- but it is still recorded, and `reconcile` still reports
    out of sync so the caller stops.
    """
    bot_ids = sorted({b for d in divergences for b in d.bot_ids})
    if not bot_ids:
        return []

    bots = list(session.execute(
        select(Bot).where(Bot.id.in_(bot_ids))
    ).scalars())

    halted = []
    for bot in bots:
        if not bot.enabled:
            continue
        bot.enabled = False
        halted.append(bot.id)
        append_audit(
            session, event_type=AUDIT_BOT_HALTED,
            payload={
                'reason': 'position diverged from the broker',
                'detail': '; '.join(
                    d.describe() for d in divergences if bot.id in d.bot_ids
                ),
            },
            bot_id=bot.id,
        )

    session.flush()
    return halted


def adopt_broker_state(
    session: Session,
    broker: BrokerAdapter,
    bot_id: int,
    note: str,
) -> list:
    """Overwrite one bot's positions with what the broker reports.

    For an operator to call once they know why the drift happened. Requires a
    `note` because a state overwrite with no recorded explanation is how the
    cause of a divergence gets lost -- the numbers stop disagreeing and nobody
    ever finds out why they did.

    Only sensible when one bot owns every affected symbol. With several bots on a
    symbol, the broker's total cannot be split between them without knowing which
    one's fills went missing, and this function does not guess.
    """
    broker_positions = {p.symbol: p for p in broker.get_positions() if p.qty != 0}

    existing = list(session.execute(
        select(PositionRow).where(PositionRow.bot_id == bot_id)
    ).scalars())
    for row in existing:
        session.delete(row)
    session.flush()

    now = datetime.now(timezone.utc)
    adopted = []
    for symbol, position in sorted(broker_positions.items()):
        row = PositionRow(
            bot_id=bot_id, symbol=symbol, qty=position.qty,
            entry_price=position.avg_entry_price, entry_time=now,
        )
        session.add(row)
        adopted.append(symbol)

    session.flush()
    append_audit(
        session, event_type=AUDIT_RECONCILIATION,
        payload={
            'action': 'adopted_broker_state', 'note': note,
            'symbols': adopted,
            'replaced': [r.symbol for r in existing],
        },
        bot_id=bot_id,
    )
    return adopted
