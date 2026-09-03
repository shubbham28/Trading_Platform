"""
Risk gate tests.

Phase 3's exit criterion: every rule deliberately breached, the order rejected,
and the correct rule named. Not a sample of the rules -- all of them. That is
enforced structurally by `test_every_registered_rule_has_a_breach_test`, which
compares the rules registered in `risk.gate.RULES` against the rules this file
actually breaches and fails if anyone adds a rule without a test for it.

Every rule also gets a second test proving it does not block an exit. That is
the property that matters more: a limit that traps you in a losing position is
worse than no limit.
"""
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from risk.contracts import (
    AccountRiskLimits, BotRiskLimits, OrderIntent, RiskContext,
)
from risk.gate import RULE_NAMES, RULES, RiskGate, is_reducing, resulting_qty

BAR = datetime(2026, 3, 2, 14, 35, tzinfo=timezone.utc)


def intent(**overrides) -> OrderIntent:
    """A plainly-safe buy. Tests override exactly the field under examination."""
    fields = dict(
        bot_id=1, symbol='AAPL', side='buy', qty=Decimal('10'),
        estimated_price=Decimal('100'), reason='test', bar_timestamp=BAR,
    )
    fields.update(overrides)
    return OrderIntent(**fields)


def context(**overrides) -> RiskContext:
    """A context with plenty of headroom on every limit.

    Chosen so that a test which overrides one field is testing that field and
    nothing else. If the baseline sat near a limit, a failure would be ambiguous.
    """
    fields = dict(
        kill_switch_engaged=False,
        account_equity=Decimal('100000'),
        account_exposure=Decimal('0'),
        account_open_positions=0,
        account_daily_pnl=Decimal('0'),
        bot_budget=Decimal('50000'),
        bot_exposure=Decimal('0'),
        bot_open_positions=0,
        bot_daily_pnl=Decimal('0'),
        existing_position_qty=Decimal('0'),
        other_bots_holding_symbol=(),
    )
    fields.update(overrides)
    return RiskContext(**fields)


def gate(**limit_overrides) -> RiskGate:
    account = AccountRiskLimits(
        max_total_exposure_pct=limit_overrides.get('max_total_exposure_pct', 100.0),
        max_daily_loss_pct=limit_overrides.get('max_daily_loss_pct', 5.0),
        max_open_positions=limit_overrides.get('account_max_open_positions', 10),
    )
    bot = BotRiskLimits(
        max_position_pct=limit_overrides.get('max_position_pct', 100.0),
        max_daily_loss=limit_overrides.get('max_daily_loss', Decimal('1000')),
        max_open_positions=limit_overrides.get('bot_max_open_positions', 5),
        max_order_value=limit_overrides.get('max_order_value', Decimal('25000')),
    )
    return RiskGate(account, bot)


# The single source of truth for what each rule needs in order to be breached,
# and what it needs in order to be an exit. Every entry produces three tests, so
# adding a rule here is how a rule becomes covered.
#
#   breach: (intent kwargs, context kwargs, gate limit kwargs)
BREACHES = {
    'account_kill_switch': (
        {}, {'kill_switch_engaged': True, 'kill_switch_reason': 'manual halt'}, {},
    ),
    'account_live_order_ceiling': (
        # A live order with no ceiling set. Zero is the default and refuses
        # everything, which is the fail-closed posture under test.
        {'mode': 'live'}, {'live_max_order_value': Decimal('0')}, {},
    ),
    'account_max_daily_loss': (
        # Down 6000 against a 5% allowance on a 100000 baseline.
        {}, {'account_equity': Decimal('94000'),
             'account_daily_pnl': Decimal('-6000')}, {},
    ),
    'account_max_total_exposure': (
        # Already at 99500 of a 100000 ceiling; a 1000 order will not fit.
        {}, {'account_exposure': Decimal('99500')}, {},
    ),
    'account_max_open_positions': (
        {}, {'account_open_positions': 10}, {'account_max_open_positions': 10},
    ),
    'bot_capital_budget': (
        {}, {'bot_exposure': Decimal('49500')}, {},
    ),
    'bot_max_daily_loss': (
        {}, {'bot_daily_pnl': Decimal('-1500')}, {'max_daily_loss': Decimal('1000')},
    ),
    'bot_max_open_positions': (
        {}, {'bot_open_positions': 5}, {'bot_max_open_positions': 5},
    ),
    'position_max_order_value': (
        # 400 x 100 = 40000, over the 25000 per-order limit.
        {'qty': Decimal('400')}, {}, {'max_order_value': Decimal('25000')},
    ),
    'position_max_position_pct': (
        # 10% of a 50000 budget is 5000; 100 x 100 = 10000.
        {'qty': Decimal('100')}, {},
        {'max_position_pct': 10.0, 'max_order_value': Decimal('100000')},
    ),
    'position_symbol_conflict': (
        {}, {'other_bots_holding_symbol': (2, 7)}, {},
    ),
}


# -- the exit criterion ----------------------------------------------------

def test_every_registered_rule_has_a_breach_test():
    """"Every rule, not a sample of them" -- enforced, not promised.

    Adding a rule to `risk.gate.RULES` without adding it to BREACHES fails here.
    Without this test, the exit criterion would decay the first time someone
    added an eleventh rule.
    """
    registered = set(RULE_NAMES)
    covered = set(BREACHES)
    assert registered == covered, (
        f'rules with no breach test: {sorted(registered - covered)}; '
        f'breach tests for unknown rules: {sorted(covered - registered)}'
    )


def test_rule_names_are_unique():
    """A duplicate name would make a blocked order's rule ambiguous."""
    assert len(RULE_NAMES) == len(set(RULE_NAMES))


def test_baseline_intent_is_allowed():
    """The control. If this failed, every breach test below would be vacuous."""
    decision = gate().evaluate(intent(), context())
    assert decision.allowed, decision.detail
    assert decision.rule is None


@pytest.mark.parametrize('rule_name', sorted(BREACHES))
def test_breaching_a_rule_blocks_the_order_and_names_that_rule(rule_name):
    """One deliberate breach per rule.

    Asserts the exact rule name, not merely that something objected. A gate that
    blocks for the wrong reason is nearly as unhelpful as one that does not
    block: the operator fixes the wrong limit and the order stays blocked.
    """
    intent_kwargs, context_kwargs, limit_kwargs = BREACHES[rule_name]
    decision = gate(**limit_kwargs).evaluate(
        intent(**intent_kwargs), context(**context_kwargs)
    )

    assert decision.blocked, f'{rule_name} did not block: {decision.detail}'
    assert decision.rule == rule_name, (
        f'expected {rule_name} to block this order, but {decision.rule} did '
        f'first: {decision.detail}'
    )
    assert decision.tier == rule_name.split('_')[0].replace('position', 'position')
    assert decision.detail, 'a blocked order must carry a reason'


@pytest.mark.parametrize('rule_name', sorted(BREACHES))
def test_no_rule_blocks_an_exit(rule_name):
    """The property that matters more than any individual limit.

    Each rule is breached exactly as above, then the order is turned into a close
    of an existing position. It must pass. A limit that can trap you inside a
    losing position is worse than no limit -- and the kill switch is included
    here, because the plan says engaging it makes bots flatten, which requires
    sells to get through.
    """
    intent_kwargs, context_kwargs, limit_kwargs = BREACHES[rule_name]

    # Long 10, selling 10: an exact close.
    exit_context = {**context_kwargs, 'existing_position_qty': Decimal('10')}
    exit_intent = {**intent_kwargs, 'side': 'sell', 'qty': Decimal('10')}

    decision = gate(**limit_kwargs).evaluate(
        intent(**exit_intent), context(**exit_context)
    )

    assert decision.allowed, (
        f'{rule_name} blocked an exit ({decision.detail}). A bot that hit this '
        'limit would be locked into the position that got it there.'
    )
    assert decision.is_reducing


@pytest.mark.parametrize('rule_name', sorted(BREACHES))
def test_a_partial_exit_is_also_never_blocked(rule_name):
    """Scaling out has to work too, not just a full close."""
    intent_kwargs, context_kwargs, limit_kwargs = BREACHES[rule_name]
    exit_context = {**context_kwargs, 'existing_position_qty': Decimal('100')}
    exit_intent = {**intent_kwargs, 'side': 'sell', 'qty': Decimal('40')}

    decision = gate(**limit_kwargs).evaluate(
        intent(**exit_intent), context(**exit_context)
    )
    assert decision.allowed, f'{rule_name} blocked a partial exit: {decision.detail}'


# -- reducing vs opening classification ------------------------------------

@pytest.mark.parametrize('existing,side,qty,expected', [
    # Flat: anything is an opening.
    (Decimal('0'), 'buy', Decimal('10'), False),
    (Decimal('0'), 'sell', Decimal('10'), False),
    # Long: opposing orders reduce, up to the position size.
    (Decimal('100'), 'sell', Decimal('40'), True),
    (Decimal('100'), 'sell', Decimal('100'), True),
    # Larger than the position: a flip, so an opening.
    (Decimal('100'), 'sell', Decimal('150'), False),
    # Same direction: pyramiding, an opening.
    (Decimal('100'), 'buy', Decimal('10'), False),
    # Short: mirror image.
    (Decimal('-100'), 'buy', Decimal('40'), True),
    (Decimal('-100'), 'buy', Decimal('100'), True),
    (Decimal('-100'), 'buy', Decimal('150'), False),
    (Decimal('-100'), 'sell', Decimal('10'), False),
])
def test_reducing_classification(existing, side, qty, expected):
    assert is_reducing(
        intent(side=side, qty=qty), context(existing_position_qty=existing)
    ) is expected


def test_a_flip_is_checked_as_an_opening():
    """Selling more than you hold opens a short, and is limited like one.

    Without this, "reducing orders bypass the limits" would be a hole big enough
    to open any position through: sell 10,000 while long 1 and the gate waves it
    past every rule.
    """
    decision = gate(max_order_value=Decimal('5000')).evaluate(
        intent(side='sell', qty=Decimal('1000')),
        # Budget and exposure ceiling deliberately generous, so the per-order
        # limit is what bites rather than the capital budget.
        context(existing_position_qty=Decimal('10'),
                bot_budget=Decimal('10000000'),
                account_equity=Decimal('10000000')),
    )
    assert decision.blocked
    assert decision.rule == 'position_max_order_value'
    assert not decision.is_reducing


def test_resulting_quantity_arithmetic():
    assert resulting_qty(
        intent(side='buy', qty=Decimal('10')), context(existing_position_qty=Decimal('5'))
    ) == Decimal('15')
    assert resulting_qty(
        intent(side='sell', qty=Decimal('10')),
        context(existing_position_qty=Decimal('5')),
    ) == Decimal('-5')


# -- fail-closed behaviour -------------------------------------------------

def test_unknown_account_daily_pnl_blocks_rather_than_passes():
    """A missing baseline means the loss is unknown, not zero.

    The one place the gate fails closed, and the reason is that the alternative
    is a risk gate that stops enforcing its most important limit precisely when
    it has lost track of the account.
    """
    decision = gate().evaluate(intent(), context(account_daily_pnl=None))
    assert decision.blocked
    assert decision.rule == 'account_max_daily_loss'
    assert 'unknown' in decision.detail


def test_unknown_bot_daily_pnl_blocks_rather_than_passes():
    decision = gate().evaluate(intent(), context(bot_daily_pnl=None))
    assert decision.blocked
    assert decision.rule == 'bot_max_daily_loss'
    assert 'unknown' in decision.detail


def test_unknown_daily_pnl_still_permits_an_exit():
    """Failing closed must not mean failing shut.

    Losing track of P&L is exactly the moment you most need to be able to get
    out of a position.
    """
    decision = gate().evaluate(
        intent(side='sell', qty=Decimal('10')),
        context(account_daily_pnl=None, bot_daily_pnl=None,
                existing_position_qty=Decimal('10')),
    )
    assert decision.allowed


# -- tier ordering ---------------------------------------------------------

def test_account_tier_is_checked_before_bot_and_position():
    """Ordering is part of the contract, because it decides the reported rule.

    Every tier is breached at once here; the account rule must be the one named.
    """
    decision = gate(
        max_order_value=Decimal('1'), bot_max_open_positions=1,
    ).evaluate(
        intent(qty=Decimal('400')),
        context(kill_switch_engaged=True, bot_exposure=Decimal('49999'),
                bot_open_positions=5),
    )
    assert decision.rule == 'account_kill_switch'
    assert decision.tier == 'account'


def test_bot_tier_is_checked_before_position():
    decision = gate(max_order_value=Decimal('1')).evaluate(
        intent(qty=Decimal('400')), context(bot_exposure=Decimal('50000')),
    )
    assert decision.rule == 'bot_capital_budget'
    assert decision.tier == 'bot'


def test_kill_switch_is_checked_first_of_all():
    """Nothing else matters when the emergency stop is on."""
    decision = gate().evaluate(
        intent(), context(kill_switch_engaged=True, account_daily_pnl=None),
    )
    assert decision.rule == 'account_kill_switch'


# -- individual rule behaviour --------------------------------------------

def test_pyramiding_is_measured_on_the_resulting_position():
    """Three orders at 40% must not build a 120% position.

    Checking only the incoming order would let each one through on its own.
    """
    g = gate(max_position_pct=50.0, max_order_value=Decimal('100000'))
    # 50% of a 50000 budget is 25000. Already holding 200 x 100 = 20000.
    decision = g.evaluate(
        intent(qty=Decimal('100')), context(existing_position_qty=Decimal('200')),
    )
    assert decision.blocked
    assert decision.rule == 'position_max_position_pct'
    assert '30000' in decision.detail


def test_exposure_is_measured_on_the_delta_not_the_notional():
    """A flip onto a smaller position genuinely reduces exposure.

    Long 100 to short 50 lowers net exposure, so an exposure ceiling should not
    object even though the order is an opening one.
    """
    decision = gate(max_total_exposure_pct=100.0).evaluate(
        intent(side='sell', qty=Decimal('150')),
        context(existing_position_qty=Decimal('100'),
                account_exposure=Decimal('100000'),
                account_equity=Decimal('100000'),
                bot_exposure=Decimal('10000')),
    )
    assert decision.allowed, decision.detail


def test_adding_to_an_existing_symbol_does_not_consume_a_position_slot():
    """Position limits count symbols, not orders."""
    decision = gate(bot_max_open_positions=1).evaluate(
        intent(qty=Decimal('1')), context(bot_open_positions=1,
                                          existing_position_qty=Decimal('10')),
    )
    assert decision.allowed, decision.detail


def test_symbol_conflict_does_not_block_adding_to_a_symbol_we_already_hold():
    """The overlap was accepted when the position was opened.

    Blocking now would freeze the bot out of managing a position it already has.
    """
    decision = gate().evaluate(
        intent(), context(other_bots_holding_symbol=(2,),
                          existing_position_qty=Decimal('10')),
    )
    assert decision.allowed, decision.detail


def test_exposure_ceiling_above_100_percent_permits_margin():
    """The limit is a percentage of equity, so over 100 is a deliberate choice."""
    # 150% of 10000 equity is a 15000 ceiling. Already at 9000, so a 5000 order
    # fits only because the ceiling is above 100% of equity.
    decision = gate(max_total_exposure_pct=150.0).evaluate(
        intent(qty=Decimal('50')),
        context(account_equity=Decimal('10000'), account_exposure=Decimal('9000')),
    )
    assert decision.allowed, decision.detail

    # The same order against a 100% ceiling does not.
    blocked = gate(max_total_exposure_pct=100.0).evaluate(
        intent(qty=Decimal('50')),
        context(account_equity=Decimal('10000'), account_exposure=Decimal('9000')),
    )
    assert blocked.rule == 'account_max_total_exposure'


def test_daily_loss_allowance_is_relative_to_the_start_of_day_baseline():
    """5% of the equity you started with, not of what is left.

    Measuring against current equity would shrink the allowance as losses
    mounted, so the limit would tighten exactly as it was being approached.
    """
    # Started at 100000, down 4900. A 5% allowance is 5000, so this fits.
    decision = gate(max_daily_loss_pct=5.0).evaluate(
        intent(),
        context(account_equity=Decimal('95100'),
                account_daily_pnl=Decimal('-4900')),
    )
    assert decision.allowed, decision.detail

    # Down 5100 does not.
    decision = gate(max_daily_loss_pct=5.0).evaluate(
        intent(),
        context(account_equity=Decimal('94900'),
                account_daily_pnl=Decimal('-5100')),
    )
    assert decision.blocked
    assert decision.rule == 'account_max_daily_loss'


def test_a_profitable_day_does_not_trip_the_loss_limit():
    decision = gate().evaluate(
        intent(),
        context(account_equity=Decimal('110000'),
                account_daily_pnl=Decimal('10000')),
    )
    assert decision.allowed, decision.detail


# -- validation ------------------------------------------------------------

@pytest.mark.parametrize('qty', [Decimal('0'), Decimal('-5')])
def test_non_positive_quantity_is_rejected_as_a_caller_bug(qty):
    """Not a risk judgement. Letting it through would put nonsense on the wire."""
    decision = gate().evaluate(intent(qty=qty), context())
    assert decision.blocked
    assert decision.rule == 'invalid_intent'
    assert decision.tier == 'validation'


def test_limits_reject_nonsensical_configuration():
    """A zero or negative limit is a misconfiguration, not a strict setting."""
    with pytest.raises(ValueError):
        AccountRiskLimits(max_daily_loss_pct=0)
    with pytest.raises(ValueError):
        BotRiskLimits(max_order_value=Decimal('-1'))
    with pytest.raises(ValueError):
        BotRiskLimits(max_open_positions=0)


def test_account_limits_read_from_the_environment():
    limits = AccountRiskLimits.from_env({
        'RISK_MAX_TOTAL_EXPOSURE_PCT': '80',
        'RISK_MAX_DAILY_LOSS_PCT': '2.5',
        'RISK_MAX_OPEN_POSITIONS': '3',
    })
    assert limits.max_total_exposure_pct == 80.0
    assert limits.max_daily_loss_pct == 2.5
    assert limits.max_open_positions == 3


def test_account_limits_fall_back_to_defaults_per_field():
    """An unset variable must not blank out the default."""
    limits = AccountRiskLimits.from_env({'RISK_MAX_OPEN_POSITIONS': '3'})
    assert limits.max_open_positions == 3
    assert limits.max_daily_loss_pct == AccountRiskLimits().max_daily_loss_pct


def test_bot_limits_come_from_the_stored_record():
    class FakeBot:
        risk_limits = {'max_position_pct': 25.0, 'max_order_value': '7500'}

    limits = BotRiskLimits.from_bot(FakeBot())
    assert limits.max_position_pct == 25.0
    assert limits.max_order_value == Decimal('7500')
    # Unspecified fields keep their defaults rather than becoming None.
    assert limits.max_open_positions == BotRiskLimits().max_open_positions


def test_flat_by_close_is_not_a_gate_rule():
    """It lives in the bot's risk limits but the strategy enforces it.

    Asserted so nobody later assumes the gate is handling it. A rule that
    silently does nothing is worse than no rule.
    """
    assert 'flat_by_close' in BotRiskLimits.model_fields
    assert not any('flat_by_close' in name for name in RULE_NAMES)


# -- live gating -----------------------------------------------------------

def test_paper_orders_are_unaffected_by_the_live_ceiling():
    """The ceiling is about real money, and paper is not real money.

    Applying it to paper would make the default (zero) stop all trading
    everywhere, which is not a safety property, just a broken system.
    """
    decision = gate().evaluate(
        intent(mode='paper'), context(live_max_order_value=Decimal('0'))
    )
    assert decision.allowed, decision.detail


def test_a_live_order_within_the_ceiling_passes_the_gate():
    decision = gate().evaluate(
        intent(mode='live', qty=Decimal('10')),        # 10 x 100 = 1000
        context(live_max_order_value=Decimal('5000')),
    )
    assert decision.allowed, decision.detail


def test_a_live_order_over_the_ceiling_is_refused():
    decision = gate().evaluate(
        intent(mode='live', qty=Decimal('100')),       # 100 x 100 = 10000
        context(live_max_order_value=Decimal('5000')),
    )
    assert decision.blocked
    assert decision.rule == 'account_live_order_ceiling'
    assert '10000' in decision.detail and '5000' in decision.detail


def test_an_unset_ceiling_says_so_rather_than_reporting_a_limit_of_zero():
    """"exceeds the 0.00 ceiling" reads like a misconfiguration.

    It is one, but the useful message is that live trading has not been turned
    on, not that the limit happens to be zero.
    """
    decision = gate().evaluate(
        intent(mode='live'), context(live_max_order_value=Decimal('0'))
    )
    assert decision.blocked
    assert 'no live order ceiling has been set' in decision.detail
    assert 'live trading is off' in decision.detail


def test_the_live_ceiling_is_a_cap_not_an_approval_question():
    """Auto-approve does not lift it.

    A ceiling that a setting can bypass is not a ceiling. Approving an order and
    permitting an order of that size are separate decisions.
    """
    decision = gate().evaluate(
        intent(mode='live', qty=Decimal('100')),
        context(live_auto_approved=True, live_max_order_value=Decimal('5000')),
    )
    assert decision.blocked
    assert decision.rule == 'account_live_order_ceiling'


def test_the_live_ceiling_does_not_block_a_live_exit():
    """Trapping someone in a live position is worse than any exposure limit."""
    decision = gate().evaluate(
        intent(mode='live', side='sell', qty=Decimal('10')),
        context(live_max_order_value=Decimal('0'),
                existing_position_qty=Decimal('10')),
    )
    assert decision.allowed, decision.detail
    assert decision.is_reducing


def test_the_live_ceiling_is_independent_of_the_bots_own_order_limit():
    """Two limits, both enforced, whichever is tighter.

    The bot's limit was tuned against paper; the live ceiling is what the
    operator stands behind for real money.
    """
    # Bot allows 25000, live ceiling allows 2000. The live ceiling bites first
    # because it is checked in the account tier.
    decision = gate(max_order_value=Decimal('25000')).evaluate(
        intent(mode='live', qty=Decimal('100')),
        context(live_max_order_value=Decimal('2000')),
    )
    assert decision.rule == 'account_live_order_ceiling'

    # And the reverse: a generous live ceiling does not lift a tight bot limit.
    decision = gate(max_order_value=Decimal('500')).evaluate(
        intent(mode='live', qty=Decimal('100')),
        context(live_max_order_value=Decimal('100000')),
    )
    assert decision.rule == 'position_max_order_value'
