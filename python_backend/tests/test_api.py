"""
API tests.

Exercises the real FastAPI app end to end against a SQLite database and a fake
data provider. Nothing here reaches Alpaca or Postgres, so the whole thing runs
offline -- which is the only way these paths get tested at all.
"""
import pytest

pytest.importorskip('fastapi', reason='fastapi not installed')

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from db.session import create_all, get_engine, reset_engine  # noqa: E402
from tests.conftest import make_daily_bars  # noqa: E402
from tests.test_interfaces import FakeDataProvider  # noqa: E402


@pytest.fixture
def client(tmp_path, monkeypatch):
    """The real app, wired to SQLite and a fake data feed."""
    url = f'sqlite+pysqlite:///{tmp_path}/api.db'
    monkeypatch.setenv('DATABASE_URL', url)
    reset_engine()
    create_all(get_engine())

    # Inject the fake provider into the lazy slot rather than patching the
    # accessor, so the accessor's own caching is part of what is exercised.
    monkeypatch.setattr(main, '_data_provider', FakeDataProvider(make_daily_bars(n=150)))

    with TestClient(main.app) as test_client:
        yield test_client

    reset_engine()


BACKTEST_BODY = {
    'symbol': 'TEST',
    'strategy_id': 'sma_crossover',
    'start_date': '2025-01-02',
    'end_date': '2025-08-01',
    'timeframe': '1Day',
    'initial_capital': 10000.0,
    'parameters': {'short_period': 5, 'long_period': 20},
}


# -- health ----------------------------------------------------------------

def test_health_reports_database_reachable(client):
    body = client.get('/health').json()
    assert body['status'] == 'ok'
    assert body['database']['reachable'] is True


def test_health_reports_degraded_when_the_database_is_unreachable(
    tmp_path, monkeypatch
):
    """A backend that cannot reach its database is not healthy.

    Bots would evaluate, decide, and lose every record of having done so.
    Reporting "ok" there is exactly the silent failure this system is built to
    avoid.
    """
    monkeypatch.setenv(
        'DATABASE_URL', 'postgresql+psycopg://u:p@127.0.0.1:1/nope'
    )
    reset_engine()
    with TestClient(main.app) as test_client:
        body = test_client.get('/health').json()
    reset_engine()

    assert body['status'] == 'degraded'
    assert body['database']['reachable'] is False
    assert 'error' in body['database']


def test_health_does_not_leak_the_database_password(tmp_path, monkeypatch):
    """A health endpoint is usually the least protected route on a service."""
    monkeypatch.setenv(
        'DATABASE_URL',
        'postgresql+psycopg://someuser:sup3rs3cret@localhost:5432/trading',
    )
    reset_engine()
    with TestClient(main.app) as test_client:
        body = test_client.get('/health').json()
    reset_engine()

    rendered = body['database']['configured_url']
    assert 'sup3rs3cret' not in rendered
    assert '***' in rendered
    assert 'someuser' in rendered, 'the user is useful; only the secret should go'


# -- backtest persistence --------------------------------------------------

def test_backtest_run_persists_and_reports_that_it_did(client):
    body = client.post('/backtest/run', json=BACKTEST_BODY).json()

    assert body['persisted'] is True, body.get('persistence_error')
    assert body['run_id'] is not None
    assert body['persistence_error'] is None


def test_stored_run_reads_back_with_its_costs_and_audit(client):
    run_id = client.post('/backtest/run', json=BACKTEST_BODY).json()['run_id']

    stored = client.get(f'/backtest/runs/{run_id}').json()
    assert stored['strategy_id'] == 'sma_crossover'
    assert stored['symbol'] == 'TEST'
    assert stored['parameters'] == {'short_period': 5, 'long_period': 20}
    # Costs travel with the result. A Sharpe ratio without them is not a result.
    assert 'slippage_bps' in stored['config']
    assert 'commission' in stored['config']
    assert 'forced_liquidations' in stored['audit']
    assert 'sharpe_ratio' in stored['metrics']


def test_runs_list_returns_what_was_run(client):
    for _ in range(3):
        client.post('/backtest/run', json=BACKTEST_BODY)

    body = client.get('/backtest/runs').json()
    assert body['count'] == 3
    ids = [r['id'] for r in body['runs']]
    assert ids == sorted(ids, reverse=True), 'newest first'
    assert body['next_before_id'] == ids[-1]


def test_runs_list_filters_by_strategy(client):
    client.post('/backtest/run', json=BACKTEST_BODY)
    client.post('/backtest/run', json={**BACKTEST_BODY,
                                       'strategy_id': 'rsi_mean_revert',
                                       'parameters': {}})

    body = client.get('/backtest/runs', params={'strategy_id': 'rsi_mean_revert'}).json()
    assert body['count'] == 1
    assert body['runs'][0]['strategy_id'] == 'rsi_mean_revert'


def test_equity_curve_is_served_separately_from_the_run(client):
    posted = client.post('/backtest/run', json=BACKTEST_BODY).json()
    run_id = posted['run_id']

    stored = client.get(f'/backtest/runs/{run_id}').json()
    assert 'equity_curve' not in stored, (
        'the curve must not ride along inside every run lookup'
    )

    curve = client.get(f'/backtest/runs/{run_id}/equity').json()
    assert curve['count'] == len(posted['equity_curve'])
    assert curve['equity_curve'][0]['bar_index'] == 0
    assert 'equity' in curve['equity_curve'][0]


def test_equity_curve_can_be_limited(client):
    run_id = client.post('/backtest/run', json=BACKTEST_BODY).json()['run_id']
    curve = client.get(f'/backtest/runs/{run_id}/equity', params={'limit': 10}).json()
    assert curve['count'] == 10


def test_unknown_run_is_a_404(client):
    assert client.get('/backtest/runs/999999').status_code == 404


def test_backtest_still_returns_results_when_persistence_fails(
    tmp_path, monkeypatch
):
    """A failed write must not fail the request, or hide itself.

    The backtest already ran and its numbers are valid. But a result that was not
    stored must not be reported as if it were -- the difference only surfaces
    later, when someone cannot find the run they remember running.
    """
    monkeypatch.setenv('DATABASE_URL', 'postgresql+psycopg://u:p@127.0.0.1:1/nope')
    reset_engine()
    monkeypatch.setattr(
        main, '_data_provider', FakeDataProvider(make_daily_bars(n=150))
    )

    with TestClient(main.app) as test_client:
        response = test_client.post('/backtest/run', json=BACKTEST_BODY)
    reset_engine()

    assert response.status_code == 200
    body = response.json()
    assert body['persisted'] is False
    assert body['persistence_error']
    assert body['run_id'] is None
    # The actual result is still there and still correct.
    assert 'sharpe_ratio' in body
    assert body['equity_curve']


def test_run_listing_reports_503_when_the_database_is_down(tmp_path, monkeypatch):
    """Unavailable is not the same as empty.

    A 200 with an empty list would read as "you have never run a backtest".
    """
    monkeypatch.setenv('DATABASE_URL', 'postgresql+psycopg://u:p@127.0.0.1:1/nope')
    reset_engine()
    with TestClient(main.app) as test_client:
        response = test_client.get('/backtest/runs')
    reset_engine()

    assert response.status_code == 503
    assert 'Database unavailable' in response.json()['detail']


# -- strategy endpoints ----------------------------------------------------

def test_strategy_list_comes_from_the_python_registry(client):
    body = client.get('/strategy/list').json()
    ids = {s['id'] for s in body['strategies']} if 'strategies' in body else {
        s['id'] for s in body
    }
    assert 'vwap_reversion' in ids
    assert 'sma_crossover' in ids


def test_strategy_run_returns_signals(client):
    body = client.post('/strategy/run', json={
        'symbol': 'TEST', 'strategy_id': 'sma_crossover',
        'start_date': '2025-01-02', 'end_date': '2025-08-01',
        'timeframe': '1Day', 'parameters': {'short_period': 5, 'long_period': 20},
    }).json()

    assert body['total_signals'] > 0
    assert body['buy_signals'] + body['sell_signals'] + body['hold_signals'] == (
        body['total_signals']
    )


# -- risk endpoints --------------------------------------------------------

def test_kill_switch_starts_disengaged(client):
    body = client.get('/risk/kill-switch').json()
    assert body['engaged'] is False
    assert body['engaged_at'] is None


def test_kill_switch_can_be_engaged_and_released(client):
    engaged = client.post(
        '/risk/kill-switch', json={'engaged': True, 'reason': 'manual halt'}
    ).json()
    assert engaged['engaged'] is True
    assert engaged['reason'] == 'manual halt'
    assert engaged['engaged_at'] is not None

    assert client.get('/risk/kill-switch').json()['engaged'] is True

    released = client.post('/risk/kill-switch', json={'engaged': False}).json()
    assert released['engaged'] is False
    assert released['engaged_at'] is None


def test_kill_switch_changes_are_audited(client):
    """"Who turned this off, and when" is the first question after an incident."""
    client.post('/risk/kill-switch', json={'engaged': True, 'reason': 'testing'})

    from db import repository
    from db.session import session_scope
    with session_scope() as session:
        entries = repository.recent_audit(session, event_type='kill_switch')

    assert len(entries) == 1
    assert entries[0].payload == {'engaged': True, 'reason': 'testing'}


def test_risk_rules_endpoint_lists_every_rule_in_evaluation_order(client):
    from risk.gate import RULE_NAMES

    body = client.get('/risk/rules').json()
    assert [r['name'] for r in body['rules']] == list(RULE_NAMES)
    assert [r['tier'] for r in body['rules'][:4]] == ['account'] * 4
    assert 'account_limits' in body
    assert 'reduce' in body['note'] or 'reduces' in body['note']


def test_risk_decisions_endpoint_is_empty_before_anything_is_evaluated(client):
    body = client.get('/risk/decisions').json()
    assert body['count'] == 0
    assert body['decisions'] == []


def test_risk_decisions_endpoint_reports_blocked_and_allowed(client):
    """Both outcomes, so a silent bot can be told apart from a blocked one."""
    from decimal import Decimal

    from db import repository
    from db.session import session_scope
    from risk.context import evaluate_and_record
    from risk.gate import RiskGate
    from tests.test_risk_gate import context as gate_context, intent as make_intent

    with session_scope() as session:
        bot = repository.create_bot(
            session, name='api-bot', strategy_id='sma_crossover',
            symbols=['AAPL'], timeframe='5Min',
            capital_budget=Decimal('50000'), parameters={}, risk_limits={},
        )
        bot_id = bot.id
        evaluate_and_record(
            session, RiskGate(), make_intent(bot_id=bot_id), gate_context()
        )
        evaluate_and_record(
            session, RiskGate(),
            make_intent(bot_id=bot_id, bar_timestamp=None),
            gate_context(kill_switch_engaged=True),
        )

    body = client.get('/risk/decisions').json()
    assert body['count'] == 2
    outcomes = {(d['allowed'], d['rule']) for d in body['decisions']}
    assert (True, None) in outcomes
    assert (False, 'account_kill_switch') in outcomes


def test_risk_endpoints_report_503_when_the_database_is_down(tmp_path, monkeypatch):
    monkeypatch.setenv('DATABASE_URL', 'postgresql+psycopg://u:p@127.0.0.1:1/nope')
    reset_engine()
    with TestClient(main.app) as test_client:
        assert test_client.get('/risk/kill-switch').status_code == 503
        assert test_client.get('/risk/decisions').status_code == 503
    reset_engine()


# -- bot endpoints ---------------------------------------------------------

BOT_BODY = {
    'name': 'sma-test',
    'strategy_id': 'sma_crossover',
    'symbols': ['AAPL'],
    'timeframe': '1Day',
    'capital_budget': 25000.0,
    'parameters': {'short_period': 5, 'long_period': 20},
    'risk_limits': {'max_order_value': 5000},
}


def test_a_bot_is_a_config_record(client):
    """Creating a bot is a row, not a code change."""
    body = client.post('/bots', json=BOT_BODY).json()

    assert body['id'] is not None
    assert body['strategy_id'] == 'sma_crossover'
    assert body['parameters'] == {'short_period': 5, 'long_period': 20}
    assert body['enabled'] is False, 'a new bot must not start enabled'

    listed = client.get('/bots').json()['bots']
    assert [b['name'] for b in listed] == ['sma-test']


def test_a_bot_naming_an_unknown_strategy_is_rejected(client):
    """Otherwise it fails at the first bar of a live session instead of here."""
    response = client.post(
        '/bots', json={**BOT_BODY, 'strategy_id': 'wishful_thinking'}
    )
    assert response.status_code == 400
    assert 'Unknown strategy' in response.json()['detail']


def test_a_bot_with_parameters_its_strategy_rejects_is_rejected(client):
    """The strategy's own validation runs before anything is stored."""
    response = client.post('/bots', json={
        **BOT_BODY, 'parameters': {'short_period': 30, 'long_period': 5},
    })
    assert response.status_code == 400
    assert 'Invalid parameters' in response.json()['detail']


def test_a_bot_needs_at_least_one_symbol(client):
    response = client.post('/bots', json={**BOT_BODY, 'symbols': []})
    assert response.status_code == 400


def test_duplicate_bot_names_are_rejected(client):
    assert client.post('/bots', json=BOT_BODY).status_code == 200
    assert client.post('/bots', json=BOT_BODY).status_code == 409


def test_enabled_only_filter(client):
    client.post('/bots', json=BOT_BODY)
    client.post('/bots', json={**BOT_BODY, 'name': 'live-one', 'enabled': True})

    assert len(client.get('/bots').json()['bots']) == 2
    on = client.get('/bots', params={'enabled_only': True}).json()['bots']
    assert [b['name'] for b in on] == ['live-one']


# -- bot management --------------------------------------------------------

def test_bot_status_distinguishes_enabled_from_running(client):
    """`enabled` is intent. Whether a runner is attached is a different fact.

    A UI that showed an enabled bot with no process as "live" would be lying
    about the most important thing on the screen.
    """
    created = client.post('/bots', json={**BOT_BODY, 'enabled': True}).json()
    status = client.get(f"/bots/{created['id']}").json()

    assert status['enabled'] is True
    assert status['runner_attached'] is False, (
        'a bot with no activity was reported as running'
    )
    assert status['last_activity_at'] is None
    assert status['open_positions'] == []


def test_bot_status_reports_a_runner_that_is_active(client):
    from decimal import Decimal

    from db import repository
    from db.session import session_scope

    created = client.post('/bots', json={**BOT_BODY, 'enabled': True}).json()
    with session_scope() as session:
        repository.append_audit(
            session, event_type='signal', payload={'action': 'hold'},
            bot_id=created['id'],
        )

    status = client.get(f"/bots/{created['id']}").json()
    assert status['runner_attached'] is True
    assert status['seconds_since_activity'] < 5


def test_bot_daily_pnl_is_none_without_a_baseline(client):
    """None, not zero. In that state the gate blocks every opening order,
    so it must not read as a flat day."""
    created = client.post('/bots', json=BOT_BODY).json()
    assert client.get(f"/bots/{created['id']}").json()['daily_pnl'] is None


def test_bot_daily_pnl_is_reported_when_snapshots_exist(client):
    from datetime import datetime, timedelta, timezone
    from decimal import Decimal

    from db.session import session_scope
    from risk.context import record_start_of_day_equity

    created = client.post('/bots', json=BOT_BODY).json()
    now = datetime.now(timezone.utc)
    with session_scope() as session:
        record_start_of_day_equity(
            session, equity=Decimal('25000'), cash=Decimal('25000'),
            bot_id=created['id'], captured_at=now - timedelta(hours=1),
        )
        record_start_of_day_equity(
            session, equity=Decimal('25400'), cash=Decimal('25400'),
            bot_id=created['id'], captured_at=now,
        )

    assert client.get(f"/bots/{created['id']}").json()['daily_pnl'] == 400.0


def test_a_bot_can_be_tuned_without_touching_code(client):
    """The Phase 5 exit criterion, in one request."""
    created = client.post('/bots', json=BOT_BODY).json()
    updated = client.patch(
        f"/bots/{created['id']}",
        json={'parameters': {'short_period': 8, 'long_period': 40}},
    ).json()

    assert updated['parameters'] == {'short_period': 8, 'long_period': 40}
    assert client.get(f"/bots/{created['id']}").json()['parameters'] == {
        'short_period': 8, 'long_period': 40
    }


def test_tuning_omits_nothing_it_was_not_asked_to_change(client):
    """Partial update. Changing one field must not blank the others."""
    created = client.post('/bots', json=BOT_BODY).json()
    client.patch(f"/bots/{created['id']}", json={'enabled': True})

    after = client.get(f"/bots/{created['id']}").json()
    assert after['enabled'] is True
    assert after['parameters'] == BOT_BODY['parameters']
    assert after['symbols'] == BOT_BODY['symbols']
    assert after['capital_budget'] == BOT_BODY['capital_budget']
    assert after['risk_limits'] == BOT_BODY['risk_limits']


def test_invalid_tuning_is_refused_before_it_is_stored(client):
    """Otherwise it fails at the first bar of the next session instead."""
    created = client.post('/bots', json=BOT_BODY).json()
    response = client.patch(
        f"/bots/{created['id']}",
        json={'parameters': {'short_period': 50, 'long_period': 5}},
    )

    assert response.status_code == 400
    assert client.get(f"/bots/{created['id']}").json()['parameters'] == (
        BOT_BODY['parameters']
    )


def test_tuning_is_audited(client):
    from db import repository
    from db.session import session_scope

    created = client.post('/bots', json=BOT_BODY).json()
    client.patch(f"/bots/{created['id']}", json={'enabled': True})

    with session_scope() as session:
        entries = repository.recent_audit(session, event_type='bot_updated')
    assert len(entries) == 1
    assert entries[0].payload == {'enabled': True}


def test_a_bot_can_be_cloned_and_retuned(client):
    """Clone, retune, run both. The point of config-driven bots."""
    created = client.post('/bots', json=BOT_BODY).json()
    clone = client.post(
        f"/bots/{created['id']}/clone",
        json={'name': 'sma-faster', 'parameters': {'short_period': 2, 'long_period': 6}},
    ).json()

    assert clone['id'] != created['id']
    assert clone['name'] == 'sma-faster'
    assert clone['strategy_id'] == created['strategy_id']
    assert clone['parameters'] == {'short_period': 2, 'long_period': 6}
    # Untouched fields carry over.
    assert clone['symbols'] == created['symbols']
    assert clone['capital_budget'] == created['capital_budget']


def test_a_clone_is_always_disabled(client):
    """A clone exists to be retuned before it trades.

    One that started enabled would be trading the parent's parameters against
    the same account before anyone had looked at it.
    """
    created = client.post('/bots', json={**BOT_BODY, 'enabled': True}).json()
    clone = client.post(
        f"/bots/{created['id']}/clone", json={'name': 'sma-copy'}
    ).json()
    assert created['enabled'] is True
    assert clone['enabled'] is False


def test_cloning_onto_an_existing_name_is_refused(client):
    created = client.post('/bots', json=BOT_BODY).json()
    response = client.post(
        f"/bots/{created['id']}/clone", json={'name': BOT_BODY['name']}
    )
    assert response.status_code == 409


def test_a_bot_can_be_deleted(client):
    created = client.post('/bots', json=BOT_BODY).json()
    assert client.delete(f"/bots/{created['id']}").status_code == 200
    assert client.get(f"/bots/{created['id']}").status_code == 404


def test_deleting_a_bot_that_holds_a_position_is_refused(client):
    """Positions cascade on delete.

    Removing the bot would drop our record while the broker carries on holding
    the real thing -- a live position nothing in the system knows about.
    """
    from datetime import datetime, timezone
    from decimal import Decimal

    from db.models import PositionRow
    from db.session import session_scope

    created = client.post('/bots', json=BOT_BODY).json()
    with session_scope() as session:
        session.add(PositionRow(
            bot_id=created['id'], symbol='AAPL', qty=Decimal('10'),
            entry_price=Decimal('150'), entry_time=datetime.now(timezone.utc),
        ))

    response = client.delete(f"/bots/{created['id']}")
    assert response.status_code == 409
    assert 'Flatten it first' in response.json()['detail']
    assert client.get(f"/bots/{created['id']}").status_code == 200


def test_bot_status_counts_blocked_orders_by_rule(client):
    """"What is my risk gate actually stopping?" answered directly."""
    from datetime import datetime, timedelta, timezone
    from decimal import Decimal

    from db.models import Order
    from db.session import session_scope

    created = client.post('/bots', json=BOT_BODY).json()
    with session_scope() as session:
        for i, rule in enumerate(
            ['account_kill_switch', 'account_kill_switch', 'bot_capital_budget']
        ):
            session.add(Order(
                bot_id=created['id'], client_order_id=f'blocked-{i}',
                symbol='AAPL', side='buy', order_type='market',
                qty=Decimal('1'), status='blocked', blocked_by_rule=rule,
                bar_timestamp=datetime.now(timezone.utc) + timedelta(minutes=i),
            ))

    counts = client.get(f"/bots/{created['id']}").json()['blocked_orders_by_rule']
    assert counts == {'account_kill_switch': 2, 'bot_capital_budget': 1}


def test_bot_list_carries_status_so_the_ui_needs_one_request(client):
    """A list that omitted status would force one request per row."""
    client.post('/bots', json=BOT_BODY)
    client.post('/bots', json={**BOT_BODY, 'name': 'second'})

    bots = client.get('/bots').json()['bots']
    assert len(bots) == 2
    for bot in bots:
        assert 'runner_attached' in bot
        assert 'open_positions' in bot
        assert 'daily_pnl' in bot


# -- audit viewer ----------------------------------------------------------

def test_audit_endpoint_returns_every_event_type(client):
    """"What happened at 10:31?" needs all of them in one place."""
    from db import repository
    from db.session import session_scope

    created = client.post('/bots', json=BOT_BODY).json()
    with session_scope() as session:
        for event_type in ('signal', 'risk_decision', 'order_submitted', 'fill'):
            repository.append_audit(
                session, event_type=event_type, payload={'x': 1},
                bot_id=created['id'], symbol='AAPL',
            )

    body = client.get('/audit').json()
    types = {e['event_type'] for e in body['entries']}
    assert {'signal', 'risk_decision', 'order_submitted', 'fill'} <= types


def test_audit_endpoint_filters_by_bot_and_event_type(client):
    from db import repository
    from db.session import session_scope

    first = client.post('/bots', json=BOT_BODY).json()
    second = client.post('/bots', json={**BOT_BODY, 'name': 'second'}).json()
    with session_scope() as session:
        repository.append_audit(session, 'signal', {'a': 1}, bot_id=first['id'])
        repository.append_audit(session, 'fill', {'b': 2}, bot_id=second['id'])

    only_first = client.get('/audit', params={'bot_id': first['id']}).json()
    assert {e['bot_id'] for e in only_first['entries']} == {first['id']}

    only_fills = client.get('/audit', params={'event_type': 'fill'}).json()
    assert {e['event_type'] for e in only_fills['entries']} == {'fill'}


def test_strategy_list_shape_is_stable(client):
    """The frontend reads `strategies` off this payload.

    Phase 2 repointed /api/strategies from Node's own registry to the engine,
    which wraps the list. The TypeScript cast hid the change and the dropdown
    was empty until Phase 5. Pinned so the shape cannot drift silently again.
    """
    body = client.get('/strategy/list').json()
    assert isinstance(body, dict) and 'strategies' in body
    assert isinstance(body['strategies'], list)

    for entry in body['strategies']:
        assert set(entry) == {'id', 'name', 'description', 'parameters'}


def test_strategy_list_exposes_real_default_parameters(client):
    """`{}` gives an operator nothing to start from."""
    body = client.get('/strategy/list').json()
    by_id = {s['id']: s for s in body['strategies']}

    sma = by_id['sma_crossover']['parameters']
    assert sma['short_period'] == 10
    assert sma['long_period'] == 30

    vwap = by_id['vwap_reversion']['parameters']
    assert vwap['ema_fast'] == 20
    assert vwap['ema_slow'] == 50
    assert vwap['stop_loss_pct'] == 1.5

    # Every strategy must offer something.
    for entry in body['strategies']:
        assert entry['parameters'], f"{entry['id']} exposes no defaults"


def test_enabling_a_bot_does_not_make_it_look_like_it_is_running(client):
    """Found by driving the UI, not by a test.

    `PATCH /bots/{id}` writes a `bot_updated` audit row. Counting every event as
    activity meant the act of enabling a bot reported it as running, with no
    process attached anywhere -- the exact misreport the status field exists to
    prevent. Configuration changes are excluded from activity now.
    """
    created = client.post('/bots', json=BOT_BODY).json()
    enabled = client.patch(f"/bots/{created['id']}", json={'enabled': True}).json()

    assert enabled['enabled'] is True
    assert enabled['runner_attached'] is False, (
        'enabling a bot reported it as running'
    )
    assert enabled['last_activity_at'] is None


def test_only_runner_events_count_as_activity(client):
    from db import repository
    from db.session import session_scope

    created = client.post('/bots', json={**BOT_BODY, 'enabled': True}).json()

    with session_scope() as session:
        # Things a person does. Not activity.
        repository.append_audit(
            session, 'bot_updated', {'enabled': True}, bot_id=created['id']
        )
        repository.append_audit(
            session, 'kill_switch', {'engaged': True}, bot_id=created['id']
        )
    assert client.get(f"/bots/{created['id']}").json()['runner_attached'] is False

    with session_scope() as session:
        # Something only a runner writes.
        repository.append_audit(
            session, 'signal', {'action': 'hold'}, bot_id=created['id']
        )
    assert client.get(f"/bots/{created['id']}").json()['runner_attached'] is True


# -- live gating -----------------------------------------------------------

def test_live_settings_default_to_off_and_say_so_plainly(client):
    """A UI must not have to infer the posture from a flag plus a number."""
    body = client.get('/live/settings').json()
    assert body['auto_approve'] is False
    assert body['max_order_value'] == 0.0
    assert body['live_trading_permitted'] is False


def test_setting_a_ceiling_permits_live_trading(client):
    body = client.post('/live/settings', json={'max_order_value': 2500}).json()
    assert body['max_order_value'] == 2500.0
    assert body['live_trading_permitted'] is True
    # Setting a ceiling is not the same as removing the human check.
    assert body['auto_approve'] is False


def test_enabling_auto_approve_without_a_note_is_refused(client):
    response = client.post('/live/settings', json={'auto_approve': True})
    assert response.status_code == 400
    assert 'requires a note' in response.json()['detail']
    assert client.get('/live/settings').json()['auto_approve'] is False


def test_enabling_auto_approve_with_a_note_is_accepted_and_recorded(client):
    body = client.post('/live/settings', json={
        'auto_approve': True, 'note': 'paper-clean for a month',
    }).json()
    assert body['auto_approve'] is True
    assert body['auto_approve_note'] == 'paper-clean for a month'
    assert body['auto_approve_enabled_at'] is not None


def test_a_zero_timeout_is_refused(client):
    response = client.post(
        '/live/settings', json={'approval_timeout_seconds': 0}
    )
    assert response.status_code == 400


def test_the_approval_queue_is_empty_before_anything_is_parked(client):
    body = client.get('/approvals').json()
    assert body['count'] == 0
    assert body['approvals'] == []
    assert body['auto_approve'] is False


def test_the_approval_queue_shows_a_parked_order_with_its_remaining_time(client):
    """How long is left matters: a request nobody can act on in time is not
    really a request."""
    from datetime import datetime, timezone
    from decimal import Decimal

    from db import repository
    from db.session import session_scope
    from risk import approvals
    from risk.contracts import OrderIntent
    from runner.router import OrderRouter
    from tests._fakes import SimBroker

    with session_scope() as session:
        bot = repository.create_bot(
            session, name='live-api-bot', strategy_id='sma_crossover',
            symbols=['AAPL'], timeframe='1Day',
            capital_budget=Decimal('50000'), parameters={}, risk_limits={},
            mode='live', enabled=True,
        )
        OrderRouter(SimBroker(mode='live'), allow_live=True).submit(
            session,
            OrderIntent(
                bot_id=bot.id, symbol='AAPL', side='buy', qty=Decimal('10'),
                estimated_price=Decimal('100'), reason='crossover',
                bar_timestamp=datetime(2026, 3, 2, 14, 35, tzinfo=timezone.utc),
                mode='live',
            ),
        )

    body = client.get('/approvals').json()
    assert body['count'] == 1
    entry = body['approvals'][0]
    assert entry['symbol'] == 'AAPL'
    assert entry['side'] == 'buy'
    assert entry['qty'] == 10.0
    assert entry['reason'] == 'crossover'
    assert entry['expires_in_seconds'] > 0


def test_rejecting_from_the_api_cancels_the_order(client):
    from datetime import datetime, timezone
    from decimal import Decimal

    from db import repository
    from db.session import session_scope
    from risk.contracts import OrderIntent
    from runner.router import OrderRouter
    from tests._fakes import SimBroker

    broker = SimBroker(mode='live')
    with session_scope() as session:
        bot = repository.create_bot(
            session, name='live-reject-bot', strategy_id='sma_crossover',
            symbols=['AAPL'], timeframe='1Day',
            capital_budget=Decimal('50000'), parameters={}, risk_limits={},
            mode='live', enabled=True,
        )
        order, _ = OrderRouter(broker, allow_live=True).submit(
            session,
            OrderIntent(
                bot_id=bot.id, symbol='AAPL', side='buy', qty=Decimal('10'),
                estimated_price=Decimal('100'), reason='crossover',
                bar_timestamp=datetime(2026, 3, 2, 14, 35, tzinfo=timezone.utc),
                mode='live',
            ),
        )
        order_id = order.id

    body = client.post(
        f'/approvals/{order_id}/reject', json={'note': 'bad print'}
    ).json()
    assert body['status'] == 'cancelled'
    assert broker.submitted == []
    assert client.get('/approvals').json()['count'] == 0


def test_rejecting_an_unknown_order_is_a_conflict_not_a_silent_success(client):
    response = client.post('/approvals/999999/reject', json={})
    assert response.status_code == 409
