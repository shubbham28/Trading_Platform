"""
The risk gate.

Every order passes through here, paper or live, bot or manual. Three tiers in a
fixed order -- account, then bot, then position -- and the first rule to object
stops the evaluation and gives its name to the decision.

TWO PROPERTIES WORTH UNDERSTANDING BEFORE CHANGING ANYTHING.

**No rule may block an exit.** Every limit here restricts orders that *increase*
exposure. If `max_daily_loss` could block a close, a bot that hit its loss limit
would be locked into the losing position that got it there -- strictly worse than
the limit not existing. The kill switch is included in this: the plan says
engaging it makes every bot "flatten and stop", and flattening means sells have
to pass. So the gate lets reducing orders straight through, and says so in the
decision.

An order larger than the position it appears to close counts as opening, because
it would flip the position rather than close it. Selling 150 while long 100 is a
new short for 50, and it is checked as one.

**Unknown is not zero.** When today's P&L cannot be determined -- no start-of-day
equity baseline -- the daily-loss rules block rather than pass. A risk gate that
treats a missing input as a comfortable one is not a risk gate. This is the only
place the gate fails closed, and it is deliberate.
"""
from decimal import Decimal
from typing import Callable, Optional

from risk.contracts import (
    AccountRiskLimits, BotRiskLimits, OrderIntent, RiskContext, RiskDecision,
)

# A rule returns a detail string when the order violates it, or None when it
# does not. Detail strings carry the actual numbers: a rule name says what
# objected, the detail says why, and both end up in audit_log.
Rule = Callable[[OrderIntent, RiskContext, AccountRiskLimits, BotRiskLimits], Optional[str]]

ACCOUNT = 'account'
BOT = 'bot'
POSITION = 'position'


def _money(value: Decimal) -> str:
    return f'{value:.2f}'


# -- classification --------------------------------------------------------

def resulting_qty(intent: OrderIntent, context: RiskContext) -> Decimal:
    """The signed position this order would leave behind."""
    return context.existing_position_qty + intent.signed_qty


def is_reducing(intent: OrderIntent, context: RiskContext) -> bool:
    """True when the order shrinks an existing position without flipping it.

    Requires all three: a position exists, the order opposes it, and the order is
    no larger than the position. Drop the third condition and a flip -- selling
    150 while long 100 -- would open a new short with every limit bypassed.
    """
    existing = context.existing_position_qty
    if existing == 0:
        return False
    # XOR, not `>`. An asymmetric comparison here reads as correct for a long
    # being sold and silently returns False for a short being bought back, so
    # shorts could never be classified as reducing -- meaning a short bot could
    # never close and every limit would apply to its exit.
    opposes = (existing > 0) != (intent.signed_qty > 0)
    return opposes and abs(intent.signed_qty) <= abs(existing)


def opens_new_symbol_slot(intent: OrderIntent, context: RiskContext) -> bool:
    """True when this order takes a position in a symbol the bot is flat in."""
    return context.existing_position_qty == 0


def exposure_delta(intent: OrderIntent, context: RiskContext) -> Decimal:
    """How much the bot's exposure in this symbol changes.

    Measured on the resulting position rather than on the order's notional, so a
    flip that lands on a smaller position is correctly seen as reducing net
    exposure even though it is an opening order.
    """
    before = abs(context.existing_position_qty)
    after = abs(resulting_qty(intent, context))
    return (after - before) * intent.estimated_price


# -- account tier ----------------------------------------------------------

def account_kill_switch(intent, context, account, bot) -> Optional[str]:
    """The emergency stop. Checked first because nothing else matters if it is on."""
    if not context.kill_switch_engaged:
        return None
    reason = context.kill_switch_reason or 'no reason recorded'
    return f'kill switch engaged ({reason}); only position-reducing orders allowed'


def account_live_order_ceiling(intent, context, account, bot) -> Optional[str]:
    """Hard cap on a single live order's notional. Paper orders are unaffected.

    Separate from `position_max_order_value`, which is the bot's own limit and
    was tuned against paper. This is the number the operator stands behind for
    real money, and it applies to every live order from every bot regardless of
    how any of them are configured.

    Defaults to zero, which refuses every live order. That is deliberate: live
    trading must not begin by inheriting a paper setup, and a ceiling nobody has
    set is not a ceiling anyone has agreed to.

    A cap, not an approval question. An order over this is refused whether or not
    a person would have approved it -- that is what makes it a ceiling.
    """
    if intent.mode != 'live':
        return None
    if intent.notional > context.live_max_order_value:
        if context.live_max_order_value == 0:
            return (
                f'live order value {_money(intent.notional)} refused: no live '
                'order ceiling has been set, so live trading is off. Set one '
                'deliberately before trading real money'
            )
        return (
            f'live order value {_money(intent.notional)} exceeds the '
            f'{_money(context.live_max_order_value)} live ceiling'
        )
    return None


def account_max_daily_loss(intent, context, account, bot) -> Optional[str]:
    """Stop opening once the account is down its daily allowance.

    Fails closed on a missing baseline. Without a start-of-day equity snapshot
    there is no way to know today's loss, and "we could not tell" must not
    resolve to "carry on".
    """
    if context.account_daily_pnl is None:
        return (
            'cannot evaluate: no start-of-day equity baseline, so today\'s P&L '
            'is unknown. Failing closed rather than assuming no loss'
        )

    baseline = context.account_equity - context.account_daily_pnl
    allowance = baseline * Decimal(str(account.max_daily_loss_pct)) / Decimal('100')
    if -context.account_daily_pnl >= allowance and allowance >= 0:
        return (
            f'account down {_money(-context.account_daily_pnl)} today against a '
            f'{_money(allowance)} allowance '
            f'({account.max_daily_loss_pct}% of {_money(baseline)})'
        )
    return None


def account_max_total_exposure(intent, context, account, bot) -> Optional[str]:
    """Cap total exposure across every bot as a percentage of equity."""
    delta = exposure_delta(intent, context)
    projected = context.account_exposure + delta
    ceiling = (
        context.account_equity * Decimal(str(account.max_total_exposure_pct))
        / Decimal('100')
    )
    if projected > ceiling:
        return (
            f'account exposure would reach {_money(projected)} against a '
            f'{_money(ceiling)} ceiling '
            f'({account.max_total_exposure_pct}% of {_money(context.account_equity)} equity)'
        )
    return None


def account_max_open_positions(intent, context, account, bot) -> Optional[str]:
    """Cap how many symbols the account holds at once, across all bots."""
    if not opens_new_symbol_slot(intent, context):
        return None
    if context.account_open_positions + 1 > account.max_open_positions:
        return (
            f'account already holds {context.account_open_positions} positions, '
            f'limit is {account.max_open_positions}'
        )
    return None


# -- bot tier --------------------------------------------------------------

def bot_capital_budget(intent, context, account, bot) -> Optional[str]:
    """A bot may not deploy more than the capital allocated to it.

    This is what makes several bots on one account safe: each one is spending
    from its own budget rather than from whatever the account happens to have.
    """
    delta = exposure_delta(intent, context)
    projected = context.bot_exposure + delta
    if projected > context.bot_budget:
        return (
            f'bot exposure would reach {_money(projected)} against a '
            f'{_money(context.bot_budget)} capital budget'
        )
    return None


def bot_max_daily_loss(intent, context, account, bot) -> Optional[str]:
    """Stop this bot opening once it is down its own daily allowance.

    Absolute dollars rather than a percentage, matching the bot config record.
    Fails closed on a missing baseline, for the same reason as the account rule.
    """
    if context.bot_daily_pnl is None:
        return (
            'cannot evaluate: no start-of-day baseline for this bot, so today\'s '
            'P&L is unknown. Failing closed rather than assuming no loss'
        )
    if -context.bot_daily_pnl >= bot.max_daily_loss:
        return (
            f'bot down {_money(-context.bot_daily_pnl)} today against a '
            f'{_money(bot.max_daily_loss)} limit'
        )
    return None


def bot_max_open_positions(intent, context, account, bot) -> Optional[str]:
    if not opens_new_symbol_slot(intent, context):
        return None
    if context.bot_open_positions + 1 > bot.max_open_positions:
        return (
            f'bot already holds {context.bot_open_positions} positions, '
            f'limit is {bot.max_open_positions}'
        )
    return None


# -- position tier ---------------------------------------------------------

def position_max_order_value(intent, context, account, bot) -> Optional[str]:
    """Cap a single order's notional.

    The percentage limits scale with the budget, so on a large budget they will
    happily pass an order that is obviously wrong. This is the absolute backstop
    against a fat-finger or a sizing bug.
    """
    if intent.notional > bot.max_order_value:
        return (
            f'order value {_money(intent.notional)} exceeds the '
            f'{_money(bot.max_order_value)} per-order limit '
            f'({intent.qty} x {_money(intent.estimated_price)})'
        )
    return None


def position_max_position_pct(intent, context, account, bot) -> Optional[str]:
    """Cap one position as a percentage of the bot's budget.

    Measured on the resulting position, so pyramiding into an existing holding
    is caught. Checking only the incoming order would let three orders at 40%
    each build a 120% position.
    """
    resulting = abs(resulting_qty(intent, context)) * intent.estimated_price
    ceiling = (
        context.bot_budget * Decimal(str(bot.max_position_pct)) / Decimal('100')
    )
    if resulting > ceiling:
        return (
            f'resulting position {_money(resulting)} exceeds {_money(ceiling)} '
            f'({bot.max_position_pct}% of the {_money(context.bot_budget)} budget)'
        )
    return None


def position_symbol_conflict(intent, context, account, bot) -> Optional[str]:
    """Do not open a position in a symbol another bot already holds.

    Two bots independently sizing a position in the same name produce double the
    intended exposure while each one stays inside its own limits. Nothing
    misbehaved, and the account is twice as concentrated as anyone chose.

    Only new positions are blocked. If this bot already holds the symbol the
    overlap was accepted earlier, and blocking now would just freeze it.
    """
    if not context.other_bots_holding_symbol:
        return None
    if not opens_new_symbol_slot(intent, context):
        return None
    others = ', '.join(str(b) for b in context.other_bots_holding_symbol)
    return (
        f'{intent.symbol} is already held by bot(s) {others}; opening a second '
        'position would double the intended exposure'
    )


# -- the rule table --------------------------------------------------------
#
# Evaluation order is part of the contract, not an implementation detail: it
# decides which rule's name a blocked order carries, and the tests assert on
# that name. Registering the rules as data rather than a chain of ifs also lets
# a meta-test assert that every rule here has a deliberate-breach test, which is
# what makes "every rule, not a sample" checkable instead of aspirational.

RULES: tuple = (
    # Account first: the emergency stop, then the loss allowance, then capacity.
    (ACCOUNT, 'account_kill_switch', account_kill_switch),
    # Second: can an order this size exist at all on a live account? Asked
    # before the loss and capacity questions because it is a standing cap rather
    # than a state-dependent one.
    (ACCOUNT, 'account_live_order_ceiling', account_live_order_ceiling),
    (ACCOUNT, 'account_max_daily_loss', account_max_daily_loss),
    (ACCOUNT, 'account_max_total_exposure', account_max_total_exposure),
    (ACCOUNT, 'account_max_open_positions', account_max_open_positions),
    # Then the bot's own allocation.
    (BOT, 'bot_capital_budget', bot_capital_budget),
    (BOT, 'bot_max_daily_loss', bot_max_daily_loss),
    (BOT, 'bot_max_open_positions', bot_max_open_positions),
    # Then this specific order and position.
    (POSITION, 'position_max_order_value', position_max_order_value),
    (POSITION, 'position_max_position_pct', position_max_position_pct),
    (POSITION, 'position_symbol_conflict', position_symbol_conflict),
)

RULE_NAMES: tuple = tuple(name for _, name, _ in RULES)


class RiskGate:
    """Evaluates an order intent against the rule table."""

    def __init__(
        self,
        account_limits: Optional[AccountRiskLimits] = None,
        bot_limits: Optional[BotRiskLimits] = None,
    ):
        self.account_limits = account_limits or AccountRiskLimits()
        self.bot_limits = bot_limits or BotRiskLimits()

    def evaluate(self, intent: OrderIntent, context: RiskContext) -> RiskDecision:
        """Rule on one order.

        Returns on the first objection, so the decision names exactly one rule.
        """
        if intent.qty <= 0:
            # Not a risk judgement. A zero or negative quantity is a caller bug,
            # and letting it through as "allowed" would put a nonsense order on
            # the wire.
            return RiskDecision(
                allowed=False, rule='invalid_intent', tier='validation',
                detail=f'quantity must be positive, got {intent.qty}',
            )

        reducing = is_reducing(intent, context)
        if reducing:
            # The exit path. No limit applies, by design -- see the module
            # docstring. Recorded as a decision so the audit trail shows the
            # order was considered and why it passed unchecked.
            return RiskDecision(
                allowed=True, is_reducing=True,
                detail=(
                    'order reduces an existing position; exposure limits do not '
                    'apply to exits'
                ),
            )

        for tier, name, rule in RULES:
            detail = rule(intent, context, self.account_limits, self.bot_limits)
            if detail is not None:
                return RiskDecision(
                    allowed=False, rule=name, tier=tier, detail=detail,
                    is_reducing=False,
                )

        return RiskDecision(
            allowed=True, is_reducing=False,
            detail=f'passed all {len(RULES)} rules',
        )
