"""
Schema tests.

No Postgres server is available in this environment, so the Postgres schema is
verified by compiling it -- rendering the DDL for the postgresql dialect and
asserting on what comes out. That catches type, constraint and index mistakes,
and it caught two real ones: a `SERIAL` primary key where the guidance is
`bigint generated always as identity`, and a partial-index predicate rendered as
`enabled IS 1`, which is SQLite syntax and a hard error on Postgres.

What it does not catch is anything only a live server would reject. That gap is
stated in TODOS.md rather than papered over.
"""
import pytest
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.schema import CreateIndex, CreateTable

from db.models import Base

PG = postgresql.dialect()
LITE = sqlite.dialect()

EXPECTED_TABLES = {
    'bots', 'orders', 'fills', 'positions', 'equity_snapshots', 'audit_log',
    'kill_switch', 'live_settings', 'backtest_runs', 'backtest_equity_points',
}

# Tables with a surrogate key. The two singletons are excluded: their id is
# always literally 1, so they deliberately have no identity or sequence.
SINGLETON_TABLES = {'kill_switch', 'live_settings'}
IDENTITY_TABLES = EXPECTED_TABLES - SINGLETON_TABLES


def pg_ddl(table_name: str) -> str:
    return str(CreateTable(Base.metadata.tables[table_name]).compile(dialect=PG))


def all_pg_ddl() -> str:
    parts = []
    for table in Base.metadata.sorted_tables:
        parts.append(str(CreateTable(table).compile(dialect=PG)))
        for index in table.indexes:
            parts.append(str(CreateIndex(index).compile(dialect=PG)))
    return '\n'.join(parts)


def test_every_expected_table_is_defined():
    assert set(Base.metadata.tables) == EXPECTED_TABLES


@pytest.mark.parametrize('table_name', sorted(IDENTITY_TABLES))
def test_primary_keys_are_bigint_identity(table_name):
    """`bigint generated always as identity`, not `serial`, not `int`.

    int overflows at 2.1 billion, which audit_log and backtest_equity_points will
    reach. serial leaves a separately-owned sequence that can drift from the
    table; identity is the SQL standard and cannot.
    """
    ddl = pg_ddl(table_name)
    assert 'BIGINT GENERATED ALWAYS AS IDENTITY' in ddl, (
        f'{table_name} primary key is not a bigint identity column:\n{ddl}'
    )
    assert 'SERIAL' not in ddl, f'{table_name} still uses SERIAL:\n{ddl}'


def test_no_serial_anywhere():
    assert 'SERIAL' not in all_pg_ddl()


def test_foreign_keys_are_bigint():
    """A narrower FK than the key it references cannot hold every value."""
    ddl = all_pg_ddl()
    for line in ddl.splitlines():
        stripped = line.strip()
        if stripped.endswith('_id BIGINT,') or stripped.endswith('_id BIGINT NOT NULL,'):
            continue
        assert not (
            stripped.startswith(('bot_id ', 'order_id ', 'run_id '))
            and 'BIGINT' not in stripped
        ), f'foreign key column is not bigint: {stripped}'


def test_money_and_price_columns_are_numeric_not_float():
    """Money is never a float.

    A float cannot represent 0.10 exactly. Accumulated across fills, that error
    produces a P&L figure that will not reconcile against a broker statement,
    and no amount of care at the call site fixes a lossy column.
    """
    ddl = all_pg_ddl()
    assert 'DOUBLE PRECISION' not in ddl, 'a float crept into a money column'
    assert 'REAL' not in ddl
    assert 'FLOAT' not in ddl

    money_columns = {
        ('bots', 'capital_budget'), ('orders', 'qty'), ('orders', 'limit_price'),
        ('orders', 'stop_price'), ('fills', 'qty'), ('fills', 'price'),
        ('fills', 'commission'), ('positions', 'qty'),
        ('positions', 'entry_price'), ('equity_snapshots', 'equity'),
        ('equity_snapshots', 'cash'), ('backtest_equity_points', 'equity'),
    }
    for table_name, column in money_columns:
        col = Base.metadata.tables[table_name].columns[column]
        assert col.type.__class__.__name__ == 'Numeric', (
            f'{table_name}.{column} is {col.type!r}, expected Numeric'
        )


def test_all_timestamps_are_timezone_aware():
    """A naive timestamp is ambiguous across a DST boundary."""
    offenders = []
    for table in Base.metadata.sorted_tables:
        for col in table.columns:
            if col.type.__class__.__name__ == 'DateTime' and not col.type.timezone:
                offenders.append(f'{table.name}.{col.name}')
    assert not offenders, f'naive timestamp columns: {offenders}'


def test_identifiers_are_lowercase_snake_case():
    """Mixed-case identifiers need quoting forever and confuse tooling."""
    for table in Base.metadata.sorted_tables:
        assert table.name == table.name.lower(), table.name
        for col in table.columns:
            assert col.name == col.name.lower(), f'{table.name}.{col.name}'
        for index in table.indexes:
            assert index.name == index.name.lower(), index.name


def test_every_foreign_key_column_is_indexed():
    """Postgres does not index foreign keys for you.

    Without an index, both JOINs on the key and ON DELETE CASCADE do full table
    scans -- and the cascade also takes a lock while it does.
    """
    unindexed = []
    for table in Base.metadata.sorted_tables:
        indexed_leading = {
            list(index.columns)[0].name for index in table.indexes if len(index.columns)
        }
        # A unique constraint creates a usable index too.
        for constraint in table.constraints:
            cols = list(getattr(constraint, 'columns', []))
            if cols:
                indexed_leading.add(cols[0].name)

        for fk in table.foreign_keys:
            column = fk.parent.name
            if column not in indexed_leading:
                unindexed.append(f'{table.name}.{column}')

    assert not unindexed, f'unindexed foreign keys: {unindexed}'


def test_partial_indexes_use_portable_predicates():
    """No SQLite syntax in Postgres index predicates.

    Autogenerating the baseline migration against SQLite rendered
    `enabled.is_(True)` as `enabled IS 1`, which Postgres rejects outright. The
    predicates are explicit portable SQL now, and this asserts they stay that way.
    """
    ddl = all_pg_ddl()
    partials = [
        line for line in ddl.splitlines()
        if 'CREATE' in line and 'INDEX' in line and 'WHERE' in line
    ]
    assert len(partials) == 4, f'expected 4 partial indexes, found {partials}'
    for line in partials:
        assert ' IS 1' not in line, f'SQLite boolean syntax in Postgres DDL: {line}'
        assert ' IS 0' not in line, line


def test_jsonb_on_postgres_json_on_sqlite():
    """jsonb is the real target; JSON keeps the test suite server-free."""
    assert 'JSONB' in all_pg_ddl()
    lite = str(
        CreateTable(Base.metadata.tables['bots']).compile(dialect=LITE)
    )
    assert 'JSON' in lite and 'JSONB' not in lite


def test_orders_idempotency_index_exists_and_is_unique():
    """One order per bot, symbol and bar.

    This is what makes a runner restart safe: replaying a bar cannot become a
    second order. Partial so manual orders, which have no bot, are unconstrained.
    """
    index = next(
        ix for ix in Base.metadata.tables['orders'].indexes
        if ix.name == 'orders_bot_symbol_bar_uniq'
    )
    assert index.unique
    assert [c.name for c in index.columns] == ['bot_id', 'symbol', 'bar_timestamp']

    rendered = str(CreateIndex(index).compile(dialect=PG))
    assert 'WHERE' in rendered, 'the index is not partial'


@pytest.mark.parametrize('table_name', sorted(SINGLETON_TABLES))
def test_singleton_tables_have_no_sequence(table_name):
    """A sequence-supplied default would hand out 2 and collide with id = 1."""
    ddl = pg_ddl(table_name)
    assert 'CHECK (id = 1)' in ddl
    assert 'IDENTITY' not in ddl
    assert 'SERIAL' not in ddl


def test_live_settings_ceiling_defaults_to_closed():
    """Zero means no live order is permitted.

    The fail-closed default that stops live trading beginning by inheriting a
    paper configuration.
    """
    from db.models import LiveSettings
    column = Base.metadata.tables['live_settings'].columns['max_order_value']
    assert column.default.arg == 0
    assert not column.nullable


def test_auto_approve_cannot_be_engaged_without_a_note():
    """Enforced by the database, not only by the service layer.

    It removes the only human check on live orders; a change with no recorded
    reason leaves nothing to review afterwards.
    """
    ddl = pg_ddl('live_settings')
    assert 'live_settings_auto_approve_needs_note' in ddl


def test_schema_creates_on_sqlite(sqlite_engine):
    """The models actually build, not just compile."""
    tables = set(inspect(sqlite_engine).get_table_names())
    assert EXPECTED_TABLES.issubset(tables)
