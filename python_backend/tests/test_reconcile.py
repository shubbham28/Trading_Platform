"""
Reconciliation tests.

The broker is where the money is; local state is a belief about it. These check
that a disagreement is noticed, recorded, and acted on, and that it is not
quietly papered over.
"""
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from db import repository
from db.models import PositionRow
from runner.reconcile import (
    AUDIT_BOT_HALTED, AUDIT_RECONCILIATION, adopt_broker_state, reconcile,
)
from tests._fakes import SimBroker

NOW = datetime(2026, 3, 2, 14, 35, tzinfo=timezone.utc)


def make_bot(db_session, name: str, enabled: bool = True):
    return repository.create_bot(
        db_session, name=name, strategy_id='sma_crossover', symbols=['AAPL'],
        timeframe='5Min', capital_budget=Decimal('50000'), parameters={},
        risk_limits={}, enabled=enabled,
    )


def give_local_position(db_session, bot_id, symbol, qty, price='100'):
    db_session.add(PositionRow(
        bot_id=bot_id, symbol=symbol, qty=Decimal(str(qty)),
        entry_price=Decimal(price), entry_time=NOW,
    ))
    db_session.flush()


# -- agreement -------------------------------------------------------------

def test_empty_books_on_both_sides_are_in_sync(db_session):
    result = reconcile(db_session, SimBroker())
    assert result.in_sync
    assert result.divergences == []


def test_matching_positions_are_in_sync(db_session):
    bot = make_bot(db_session, 'recon-bot')
    give_local_position(db_session, bot.id, 'AAPL', 10)

    broker = SimBroker()
    broker.seed_position('AAPL', 10, '100')

    assert reconcile(db_session, broker).in_sync


def test_two_bots_on_one_symbol_must_sum_to_the_broker_total(db_session):
    """The broker has never heard of bots.

    Two bots holding AAPL appear to it as one position, so the check is that our
    per-bot rows sum to the broker's figure -- comparing per bot would report a
    divergence on a perfectly consistent book.
    """
    first = make_bot(db_session, 'bot-a')
    second = make_bot(db_session, 'bot-b')
    give_local_position(db_session, first.id, 'AAPL', 6)
    give_local_position(db_session, second.id, 'AAPL', 4)

    broker = SimBroker()
    broker.seed_position('AAPL', 10, '100')

    assert reconcile(db_session, broker).in_sync


def test_reconciliation_is_audited_even_when_in_sync(db_session):
    """"We checked and it was fine" is a fact worth keeping."""
    reconcile(db_session, SimBroker())
    entries = repository.recent_audit(db_session, event_type=AUDIT_RECONCILIATION)
    assert len(entries) == 1
    assert entries[0].payload['in_sync'] is True


# -- disagreement ----------------------------------------------------------

def test_a_quantity_mismatch_is_detected_and_described(db_session):
    bot = make_bot(db_session, 'recon-bot')
    give_local_position(db_session, bot.id, 'AAPL', 10)

    broker = SimBroker()
    broker.seed_position('AAPL', 7, '100')

    result = reconcile(db_session, broker)
    assert not result.in_sync
    divergence = result.divergences[0]
    assert divergence.symbol == 'AAPL'
    assert divergence.broker_qty == Decimal('7')
    assert divergence.local_qty == Decimal('10')
    assert divergence.difference == Decimal('-3')
    assert 'broker says 7' in divergence.describe()


def test_a_position_only_the_broker_knows_about_is_a_divergence(db_session):
    """Usually a manual trade, or a fill we never recorded."""
    result = reconcile(db_session, SimBroker())
    assert result.in_sync

    broker = SimBroker()
    broker.seed_position('MSFT', 5, '400')
    result = reconcile(db_session, broker)

    assert not result.in_sync
    assert result.divergences[0].symbol == 'MSFT'
    assert result.divergences[0].local_qty == Decimal('0')
    assert result.divergences[0].bot_ids == ()


def test_a_position_only_we_know_about_is_a_divergence(db_session):
    """The dangerous direction: we think we are exposed and we are not.

    Every risk limit is then being computed against a position that does not
    exist, so the bot is both mis-measuring its exposure and unable to exit
    something it does not hold.
    """
    bot = make_bot(db_session, 'recon-bot')
    give_local_position(db_session, bot.id, 'AAPL', 10)

    result = reconcile(db_session, SimBroker())
    assert not result.in_sync
    assert result.divergences[0].broker_qty == Decimal('0')
    assert result.divergences[0].bot_ids == (bot.id,)


def test_a_divergence_halts_the_bots_that_hold_the_symbol(db_session):
    bot = make_bot(db_session, 'doomed')
    other = make_bot(db_session, 'untouched')
    give_local_position(db_session, bot.id, 'AAPL', 10)
    give_local_position(db_session, other.id, 'MSFT', 5)

    broker = SimBroker()
    broker.seed_position('AAPL', 3, '100')
    broker.seed_position('MSFT', 5, '400')

    result = reconcile(db_session, broker)

    assert result.halted_bot_ids == [bot.id]
    db_session.expire_all()
    assert repository.get_bot(db_session, bot.id).enabled is False
    assert repository.get_bot(db_session, other.id).enabled is True, (
        'a bot with no divergence was halted'
    )


def test_halting_is_persisted_not_just_in_memory(db_session):
    """`bots.enabled` is what the runner reads, and it survives a restart.

    A bot halted only inside a process that then restarts is not halted.
    """
    bot = make_bot(db_session, 'doomed')
    give_local_position(db_session, bot.id, 'AAPL', 10)
    reconcile(db_session, SimBroker())

    db_session.expire_all()
    assert repository.get_bot(db_session, bot.id).enabled is False


def test_a_halt_records_why(db_session):
    bot = make_bot(db_session, 'doomed')
    give_local_position(db_session, bot.id, 'AAPL', 10)
    reconcile(db_session, SimBroker())

    entries = repository.recent_audit(db_session, event_type=AUDIT_BOT_HALTED)
    assert len(entries) == 1
    assert entries[0].bot_id == bot.id
    assert 'diverged' in entries[0].payload['reason']
    assert 'AAPL' in entries[0].payload['detail']


def test_divergences_are_audited_with_both_sides_of_the_disagreement(db_session):
    bot = make_bot(db_session, 'doomed')
    give_local_position(db_session, bot.id, 'AAPL', 10)

    broker = SimBroker()
    broker.seed_position('AAPL', 7, '100')
    reconcile(db_session, broker)

    payload = repository.recent_audit(
        db_session, event_type=AUDIT_RECONCILIATION
    )[0].payload
    assert payload['in_sync'] is False
    assert payload['broker_positions'] == {'AAPL': '7'}
    assert payload['local_positions'] == {'AAPL': '10'}
    assert payload['divergences'][0]['difference'] == '-3'


def test_halting_can_be_switched_off_for_a_read_only_check(db_session):
    """Reporting without acting, for a dashboard or a dry run."""
    bot = make_bot(db_session, 'safe')
    give_local_position(db_session, bot.id, 'AAPL', 10)

    result = reconcile(db_session, SimBroker(), halt_on_divergence=False)
    assert not result.in_sync
    assert result.halted_bot_ids == []
    db_session.expire_all()
    assert repository.get_bot(db_session, bot.id).enabled is True


# -- deliberate recovery ---------------------------------------------------

def test_broker_state_is_not_adopted_automatically(db_session):
    """Detect and halt, never silently repair.

    Auto-adopting would let a bot that lost track of a position carry on with
    corrected figures while the cause -- a missed fill, a manual trade, a bug --
    goes uninvestigated.
    """
    bot = make_bot(db_session, 'doomed')
    give_local_position(db_session, bot.id, 'AAPL', 10)

    broker = SimBroker()
    broker.seed_position('AAPL', 3, '100')
    reconcile(db_session, broker)

    db_session.expire_all()
    row = db_session.execute(select(PositionRow)).scalar_one()
    assert row.qty == Decimal('10'), 'local state was overwritten without being asked'


def test_adopting_broker_state_replaces_the_bots_positions(db_session):
    bot = make_bot(db_session, 'recovering')
    give_local_position(db_session, bot.id, 'AAPL', 10)
    give_local_position(db_session, bot.id, 'TSLA', 3)

    broker = SimBroker()
    broker.seed_position('AAPL', 3, '105')

    adopted = adopt_broker_state(
        db_session, broker, bot.id, note='missed a partial fill during a restart'
    )

    assert adopted == ['AAPL']
    rows = list(db_session.execute(select(PositionRow)).scalars())
    assert len(rows) == 1
    assert rows[0].symbol == 'AAPL'
    assert rows[0].qty == Decimal('3')
    assert rows[0].entry_price == Decimal('105')


def test_adopting_broker_state_records_the_explanation(db_session):
    """A state overwrite with no recorded reason loses the cause for good."""
    bot = make_bot(db_session, 'recovering')
    give_local_position(db_session, bot.id, 'AAPL', 10)

    adopt_broker_state(db_session, SimBroker(), bot.id, note='closed by hand')

    entries = [
        e for e in repository.recent_audit(
            db_session, event_type=AUDIT_RECONCILIATION
        )
        if e.payload.get('action') == 'adopted_broker_state'
    ]
    assert len(entries) == 1
    assert entries[0].payload['note'] == 'closed by hand'
    assert entries[0].payload['replaced'] == ['AAPL']


def test_adopting_an_empty_broker_book_flattens_local_state(db_session):
    """Someone closed everything by hand."""
    bot = make_bot(db_session, 'recovering')
    give_local_position(db_session, bot.id, 'AAPL', 10)

    assert adopt_broker_state(
        db_session, SimBroker(), bot.id, note='flattened manually'
    ) == []
    assert list(db_session.execute(select(PositionRow)).scalars()) == []


def test_quantities_are_formatted_consistently_regardless_of_source(db_session):
    """A numeric column and a broker must not describe the same book differently.

    `numeric(18,8)` returns Decimal('10.00000000') where a broker returns
    Decimal('10'), so without normalising, two audit rows describing an identical
    book would not compare equal.
    """
    from runner.reconcile import qty_str

    assert qty_str(Decimal('10.00000000')) == '10'
    assert qty_str(Decimal('10')) == '10'
    assert qty_str(Decimal('-3.00000000')) == '-3'
    assert qty_str(Decimal('0.5')) == '0.5'
    # No scientific notation on round numbers.
    assert 'E' not in qty_str(Decimal('1000'))
    assert qty_str(Decimal('1000')) == '1000'
