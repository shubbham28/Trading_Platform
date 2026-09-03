"""
Risk context and audit tests.

The gate is pure; this covers the part that reads the database and the broker,
and the part that writes the ruling down. The exit criterion says a blocked
order must be recorded "with the correct rule name in audit_log", which is what
`test_blocked_order_is_audited_with_its_rule` checks for every rule.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from db import repository
from db.models import AuditLog, Order, PositionRow
from risk.context import (
    AUDIT_RISK_DECISION, build_context, client_order_id_for, evaluate_and_record,
    exchange_today, latest_equity, record_start_of_day_equity, start_of_day_equity,
)
from risk.contracts import AccountRiskLimits, BotRiskLimits, OrderIntent
from risk.gate import RULE_NAMES, RiskGate
from tests.test_interfaces import FakeBroker
from tests.test_risk_gate import BREACHES, context as gate_context, intent as make_intent

BAR = datetime(2026, 3, 2, 14, 35, tzinfo=timezone.utc)


@pytest.fixture
def bot(db_session):
    return repository.create_bot(
        db_session, name='risk-bot', strategy_id='sma_crossover',
        symbols=['AAPL'], timeframe='5Min', capital_budget=Decimal('50000'),
        parameters={}, risk_limits={'max_order_value': '25000'},
    )


# -- context assembly ------------------------------------------------------

def test_context_reads_account_state_from_the_broker(db_session, bot):
    """The broker is the authority on account equity and market exposure."""
    broker = FakeBroker(equity='75000')
    record_start_of_day_equity(
        db_session, equity=Decimal('75000'), cash=Decimal('75000')
    )

    ctx = build_context(db_session, broker, bot, 'AAPL')

    assert ctx.account_equity == Decimal('75000')
    assert ctx.account_daily_pnl == Decimal('0')
    assert ctx.kill_switch_engaged is False


def test_context_reports_unknown_daily_pnl_when_no_baseline_exists(
    db_session, bot
):
    """No snapshot means unknown, which the gate treats as a reason to stop."""
    ctx = build_context(db_session, FakeBroker(), bot, 'AAPL')
    assert ctx.account_daily_pnl is None
    assert ctx.bot_daily_pnl is None

    decision = RiskGate().evaluate(make_intent(), ctx)
    assert decision.blocked
    assert decision.rule == 'account_max_daily_loss'


def test_account_daily_pnl_is_broker_equity_against_the_baseline(db_session, bot):
    record_start_of_day_equity(
        db_session, equity=Decimal('80000'), cash=Decimal('80000')
    )
    ctx = build_context(db_session, FakeBroker(equity='77500'), bot, 'AAPL')
    assert ctx.account_daily_pnl == Decimal('-2500')


def test_bot_daily_pnl_comes_from_snapshot_pairs(db_session, bot):
    """No live source of per-bot equity exists, so both ends are snapshots."""
    now = datetime.now(timezone.utc)
    record_start_of_day_equity(
        db_session, equity=Decimal('50000'), cash=Decimal('50000'),
        bot_id=bot.id, captured_at=now - timedelta(hours=2),
    )
    record_start_of_day_equity(
        db_session, equity=Decimal('49200'), cash=Decimal('49200'),
        bot_id=bot.id, captured_at=now,
    )

    ctx = build_context(db_session, FakeBroker(), bot, 'AAPL')
    assert ctx.bot_daily_pnl == Decimal('-800')


def test_a_single_bot_snapshot_yields_zero_not_unknown(db_session, bot):
    """One snapshot is both the baseline and the latest, so P&L is zero so far."""
    record_start_of_day_equity(
        db_session, equity=Decimal('50000'), cash=Decimal('50000'), bot_id=bot.id
    )
    ctx = build_context(db_session, FakeBroker(), bot, 'AAPL')
    assert ctx.bot_daily_pnl == Decimal('0')


def test_bot_exposure_is_cost_basis_not_market_value(db_session, bot):
    """A capital budget is money committed, not the market's current opinion.

    Using market value would let a bot deploy more than its allocation whenever
    its existing holdings appreciated.
    """
    db_session.add(PositionRow(
        bot_id=bot.id, symbol='AAPL', qty=Decimal('100'),
        entry_price=Decimal('150'), entry_time=BAR,
    ))
    db_session.flush()

    ctx = build_context(db_session, FakeBroker(), bot, 'AAPL')
    assert ctx.bot_exposure == Decimal('15000')  # 100 x entry, not x mark
    assert ctx.bot_open_positions == 1
    assert ctx.existing_position_qty == Decimal('100')


def test_short_position_exposure_uses_absolute_quantity(db_session, bot):
    db_session.add(PositionRow(
        bot_id=bot.id, symbol='AAPL', qty=Decimal('-100'),
        entry_price=Decimal('150'), entry_time=BAR,
    ))
    db_session.flush()

    ctx = build_context(db_session, FakeBroker(), bot, 'AAPL')
    assert ctx.bot_exposure == Decimal('15000')
    assert ctx.existing_position_qty == Decimal('-100')


def test_context_finds_other_bots_holding_the_same_symbol(db_session, bot):
    """The input to the symbol-conflict rule."""
    other = repository.create_bot(
        db_session, name='other-bot', strategy_id='rsi_mean_revert',
        symbols=['AAPL'], timeframe='5Min', capital_budget=Decimal('10000'),
        parameters={}, risk_limits={},
    )
    db_session.add(PositionRow(
        bot_id=other.id, symbol='AAPL', qty=Decimal('50'),
        entry_price=Decimal('100'), entry_time=BAR,
    ))
    db_session.flush()

    ctx = build_context(db_session, FakeBroker(), bot, 'AAPL')
    assert ctx.other_bots_holding_symbol == (other.id,)

    # A symbol nobody else holds is not a conflict.
    assert build_context(
        db_session, FakeBroker(), bot, 'MSFT'
    ).other_bots_holding_symbol == ()


def test_kill_switch_state_reaches_the_context(db_session, bot):
    repository.set_kill_switch(db_session, True, reason='market halted')
    ctx = build_context(db_session, FakeBroker(), bot, 'AAPL')
    assert ctx.kill_switch_engaged is True
    assert ctx.kill_switch_reason == 'market halted'


def test_yesterdays_snapshot_is_not_todays_baseline(db_session, bot):
    """A stale baseline would compare today's equity against another day.

    The limit would then be measured over two sessions, and a bad yesterday
    would spend today's allowance.
    """
    yesterday = datetime.now(timezone.utc) - timedelta(days=1)
    record_start_of_day_equity(
        db_session, equity=Decimal('90000'), cash=Decimal('90000'),
        captured_at=yesterday,
    )
    assert start_of_day_equity(db_session) is None

    ctx = build_context(db_session, FakeBroker(equity='75000'), bot, 'AAPL')
    assert ctx.account_daily_pnl is None


def test_latest_equity_picks_the_most_recent_snapshot(db_session, bot):
    now = datetime.now(timezone.utc)
    for offset, equity in ((3, '100'), (2, '200'), (1, '300')):
        record_start_of_day_equity(
            db_session, equity=Decimal(equity), cash=Decimal(equity),
            bot_id=bot.id, captured_at=now - timedelta(hours=offset),
        )
    assert latest_equity(db_session, bot_id=bot.id) == Decimal('300')
    assert start_of_day_equity(db_session, bot_id=bot.id) == Decimal('100')


def test_exchange_today_uses_the_exchange_timezone_not_the_server(db_session):
    """A UTC server rolls over mid-evening in New York.

    Using the server's date would reset a daily loss limit part-way through an
    extended-hours session.
    """
    # 01:30 UTC on the 3rd is still the evening of the 2nd in New York.
    late_utc = datetime(2026, 3, 3, 1, 30, tzinfo=timezone.utc)
    assert exchange_today(late_utc).isoformat() == '2026-03-02'


# -- audit trail -----------------------------------------------------------

def test_allowed_decisions_are_audited_too(db_session, bot):
    """"Why did this bot do nothing all afternoon?" needs the passes recorded.

    An audit trail that only keeps refusals cannot tell a blocked bot from one
    that never had a signal.
    """
    ctx = gate_context()
    decision, order = evaluate_and_record(
        db_session, RiskGate(), make_intent(bot_id=bot.id), ctx
    )
    assert decision.allowed
    assert order is None

    entries = repository.recent_audit(db_session, event_type=AUDIT_RISK_DECISION)
    assert len(entries) == 1
    assert entries[0].payload['allowed'] is True


@pytest.mark.parametrize('rule_name', sorted(BREACHES))
def test_blocked_order_is_audited_with_its_rule(db_session, bot, rule_name):
    """The exit criterion, end to end, for every rule.

    Breach the rule, and assert the refusal reaches `audit_log` naming that rule,
    with the inputs that produced it.
    """
    intent_kwargs, context_kwargs, limit_kwargs = BREACHES[rule_name]
    account = AccountRiskLimits(
        max_total_exposure_pct=limit_kwargs.get('max_total_exposure_pct', 100.0),
        max_daily_loss_pct=limit_kwargs.get('max_daily_loss_pct', 5.0),
        max_open_positions=limit_kwargs.get('account_max_open_positions', 10),
    )
    bot_limits = BotRiskLimits(
        max_position_pct=limit_kwargs.get('max_position_pct', 100.0),
        max_daily_loss=limit_kwargs.get('max_daily_loss', Decimal('1000')),
        max_open_positions=limit_kwargs.get('bot_max_open_positions', 5),
        max_order_value=limit_kwargs.get('max_order_value', Decimal('25000')),
    )

    decision, order = evaluate_and_record(
        db_session,
        RiskGate(account, bot_limits),
        make_intent(bot_id=bot.id, **intent_kwargs),
        gate_context(**context_kwargs),
    )

    assert decision.blocked
    assert decision.rule == rule_name

    entry = repository.recent_audit(
        db_session, event_type=AUDIT_RISK_DECISION
    )[0]
    assert entry.payload['rule'] == rule_name, (
        f'audit_log recorded {entry.payload["rule"]!r}, expected {rule_name!r}'
    )
    assert entry.payload['allowed'] is False
    assert entry.payload['detail']
    assert entry.bot_id == bot.id
    assert entry.symbol == 'AAPL'

    # The order row carries the same rule, so refusals are queryable alongside
    # real orders rather than living only in the audit log.
    assert order is not None
    assert order.status == 'blocked'
    assert order.blocked_by_rule == rule_name


def test_audit_payload_carries_the_inputs_that_produced_the_decision(
    db_session, bot
):
    """A logged conclusion without its inputs cannot be re-derived or disputed."""
    decision, _ = evaluate_and_record(
        db_session, RiskGate(),
        make_intent(bot_id=bot.id),
        gate_context(kill_switch_engaged=True, kill_switch_reason='halt'),
    )
    payload = repository.recent_audit(
        db_session, event_type=AUDIT_RISK_DECISION
    )[0].payload

    assert payload['intent']['symbol'] == 'AAPL'
    assert payload['intent']['qty'] == '10'
    assert payload['intent']['notional'] == '1000'
    assert payload['context']['kill_switch_engaged'] is True
    assert payload['context']['account_equity'] == '100000'
    assert payload['context']['bot_budget'] == '50000'


def test_invalid_intent_is_audited_but_not_written_to_orders(db_session, bot):
    """A caller bug is not a risk refusal, and the orders table would reject it.

    `orders.qty > 0` is a check constraint, so a zero-quantity row cannot be
    written even if it were desirable.
    """
    decision, order = evaluate_and_record(
        db_session, RiskGate(),
        make_intent(bot_id=bot.id, qty=Decimal('0')), gate_context(),
    )
    assert decision.rule == 'invalid_intent'
    assert order is None
    assert repository.recent_audit(db_session, event_type=AUDIT_RISK_DECISION)


def test_client_order_id_is_deterministic_for_a_bot_bar_and_side():
    """A replayed bar produces the same key, so the broker deduplicates."""
    first = client_order_id_for(make_intent(bot_id=3, bar_timestamp=BAR))
    second = client_order_id_for(make_intent(bot_id=3, bar_timestamp=BAR))
    assert first == second
    assert 'bot3' in first and 'AAPL' in first

    # A different bar, side, or bot is a different order.
    assert first != client_order_id_for(
        make_intent(bot_id=3, bar_timestamp=BAR + timedelta(minutes=5))
    )
    assert first != client_order_id_for(
        make_intent(bot_id=3, bar_timestamp=BAR, side='sell')
    )
    assert first != client_order_id_for(make_intent(bot_id=4, bar_timestamp=BAR))


def test_manual_orders_get_a_unique_key():
    """No bar to key on, so a random id rather than a colliding constant."""
    a = client_order_id_for(make_intent(bot_id=None, bar_timestamp=None))
    b = client_order_id_for(make_intent(bot_id=None, bar_timestamp=None))
    assert a != b
    assert a.startswith('manual-')


def test_two_blocked_decisions_on_the_same_bar_do_not_collide(db_session, bot):
    """The idempotency index covers blocked orders too.

    One decision per bot, symbol and bar -- a refusal occupies that slot, so a
    replay cannot produce a second row.
    """
    from sqlalchemy.exc import IntegrityError

    evaluate_and_record(
        db_session, RiskGate(),
        make_intent(bot_id=bot.id, bar_timestamp=BAR),
        gate_context(kill_switch_engaged=True),
    )

    # `evaluate_and_record` flushes, so the constraint fires inside the second
    # call rather than at an explicit flush afterwards.
    with pytest.raises(IntegrityError):
        evaluate_and_record(
            db_session, RiskGate(),
            make_intent(bot_id=bot.id, bar_timestamp=BAR),
            gate_context(kill_switch_engaged=True),
        )


def test_runner_can_detect_a_replayed_bar_before_recording(db_session, bot):
    """The pattern Phase 4's runner must use.

    The idempotency index protects the data, but hitting it raises, which would
    crash a runner rather than let it skip a bar it has already handled. The
    check comes first: `find_order_for_bar` returns the existing decision, and
    the runner moves on.
    """
    evaluate_and_record(
        db_session, RiskGate(),
        make_intent(bot_id=bot.id, bar_timestamp=BAR),
        gate_context(kill_switch_engaged=True),
    )

    already = repository.find_order_for_bar(db_session, bot.id, 'AAPL', BAR)
    assert already is not None
    assert already.status == 'blocked'
    assert already.blocked_by_rule == 'account_kill_switch'


def test_blocked_orders_are_queryable_by_rule(db_session, bot):
    """The operational question is "what is my gate actually stopping?"."""
    for i, (rule_name, breach) in enumerate(sorted(BREACHES.items())[:3]):
        _, _, limit_kwargs = breach
        evaluate_and_record(
            db_session, RiskGate(),
            make_intent(bot_id=bot.id, bar_timestamp=BAR + timedelta(minutes=5 * i)),
            gate_context(kill_switch_engaged=True),
        )
    db_session.flush()

    blocked = db_session.execute(
        select(Order).where(Order.status == 'blocked')
    ).scalars().all()
    assert len(blocked) == 3
    assert {o.blocked_by_rule for o in blocked} == {'account_kill_switch'}
