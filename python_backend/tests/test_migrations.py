"""
Migration tests.

The migration and the models are two descriptions of the same schema, and the
whole risk is that they drift. These tests migrate a database, then compare what
was built against what the models say, so drift fails a test instead of
surfacing as a confusing production error.

Postgres is verified by rendering its DDL offline (`alembic upgrade --sql`),
which needs no server. That is how the `enabled IS 1` predicate was caught: it
compiles fine against SQLite and is a syntax error on Postgres.
"""
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect

from db.models import Base

BACKEND_ROOT = Path(__file__).resolve().parent.parent
PYTHON = sys.executable


def alembic(*args, database_url: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [PYTHON, '-m', 'alembic', *args],
        cwd=BACKEND_ROOT,
        env={'PATH': '/usr/bin:/bin', 'DATABASE_URL': database_url,
             'HOME': str(Path.home())},
        capture_output=True, text=True,
    )


@pytest.fixture
def sqlite_url(tmp_path) -> str:
    return f'sqlite+pysqlite:///{tmp_path}/migrated.db'


def test_upgrade_creates_the_schema(sqlite_url):
    result = alembic('upgrade', 'head', database_url=sqlite_url)
    assert result.returncode == 0, result.stderr

    engine = create_engine(sqlite_url)
    tables = set(inspect(engine).get_table_names())
    engine.dispose()

    expected = set(Base.metadata.tables) | {'alembic_version'}
    assert tables == expected


def test_migration_matches_the_models(sqlite_url):
    """No drift between the migration and the models.

    Migrating and then asking Alembic to autogenerate again must find nothing to
    do. If it finds a difference, the two descriptions of the schema disagree and
    one of them is wrong.
    """
    assert alembic('upgrade', 'head', database_url=sqlite_url).returncode == 0

    check = alembic('check', database_url=sqlite_url)
    assert check.returncode == 0, (
        'the migration and the models describe different schemas:\n'
        f'{check.stdout}\n{check.stderr}'
    )


def test_downgrade_removes_everything(sqlite_url):
    """A baseline that cannot be undone cannot be tested against."""
    assert alembic('upgrade', 'head', database_url=sqlite_url).returncode == 0
    assert alembic('downgrade', 'base', database_url=sqlite_url).returncode == 0

    engine = create_engine(sqlite_url)
    tables = set(inspect(engine).get_table_names())
    engine.dispose()
    assert tables == {'alembic_version'}


def test_upgrade_is_repeatable_after_downgrade(sqlite_url):
    for _ in range(2):
        assert alembic('upgrade', 'head', database_url=sqlite_url).returncode == 0
        assert alembic('downgrade', 'base', database_url=sqlite_url).returncode == 0


def postgres_ddl() -> str:
    """The Postgres DDL, rendered offline. No server involved."""
    result = alembic(
        'upgrade', 'head', '--sql',
        database_url='postgresql+psycopg://u:p@localhost:5432/db',
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_postgres_ddl_renders():
    ddl = postgres_ddl()
    assert 'CREATE TABLE bots' in ddl
    assert ddl.count('CREATE TABLE') == len(Base.metadata.tables) + 1  # + alembic_version


def test_postgres_ddl_has_no_sqlite_syntax():
    """The regression guard for the bug this file exists to prevent.

    Autogenerating the baseline against SQLite rendered a boolean predicate as
    `enabled IS 1`. That is valid SQLite and a hard syntax error on Postgres, so
    the migration would have failed on the only database it was meant for.
    """
    ddl = postgres_ddl()
    assert ' IS 1' not in ddl, 'SQLite boolean comparison rendered into Postgres DDL'
    assert ' IS 0' not in ddl
    assert '(CURRENT_TIMESTAMP)' not in ddl, (
        "SQLite's timestamp default literal baked into Postgres DDL"
    )


def test_postgres_ddl_uses_identity_and_jsonb():
    ddl = postgres_ddl()
    assert 'SERIAL' not in ddl
    assert ddl.count('BIGINT GENERATED ALWAYS AS IDENTITY') == 8
    assert 'JSONB' in ddl


def test_postgres_ddl_creates_the_partial_indexes():
    ddl = postgres_ddl()
    partial = [
        line for line in ddl.splitlines()
        if 'INDEX' in line and 'WHERE' in line
    ]
    assert len(partial) == 4, partial
