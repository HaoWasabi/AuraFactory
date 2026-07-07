"""Unit tests for Database.run_migrations() — idempotent migration tracking."""
import pytest
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, call, patch
import tempfile
import os

from app.database import Database


def make_mock_pool(applied_filenames: list[str] | None = None):
    """Build a mock asyncpg pool whose acquire() returns a mock connection."""
    if applied_filenames is None:
        applied_filenames = []

    # Each "row" returned by conn.fetch needs to support r["filename"]
    applied_rows = []
    for name in applied_filenames:
        row = MagicMock()
        row.__getitem__ = MagicMock(side_effect=lambda k, n=name: n if k == "filename" else None)
        applied_rows.append(row)

    conn = MagicMock()
    conn.execute = AsyncMock(return_value="OK")
    conn.fetch = AsyncMock(return_value=applied_rows)

    # transaction() is an async context manager
    tx_cm = MagicMock()
    tx_cm.__aenter__ = AsyncMock(return_value=None)
    tx_cm.__aexit__ = AsyncMock(return_value=False)
    conn.transaction = MagicMock(return_value=tx_cm)

    # acquire() is an async context manager that yields conn
    acquire_cm = MagicMock()
    acquire_cm.__aenter__ = AsyncMock(return_value=conn)
    acquire_cm.__aexit__ = AsyncMock(return_value=False)

    pool = MagicMock()
    pool.acquire = MagicMock(return_value=acquire_cm)

    return pool, conn


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def write_sql_files(dir_path: Path, files: dict[str, str]):
    """Write {filename: sql_content} into dir_path."""
    for name, sql in files.items():
        (dir_path / name).write_text(sql)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_creates_schema_migrations_table():
    """CREATE TABLE IF NOT EXISTS schema_migrations is executed first."""
    pool, conn = make_mock_pool()
    db = Database()
    db.pool = pool

    with tempfile.TemporaryDirectory() as tmpdir:
        write_sql_files(Path(tmpdir), {"001_init.sql": "CREATE TABLE foo (id SERIAL);"})
        await db.run_migrations(tmpdir)

    # First execute call must contain CREATE TABLE IF NOT EXISTS schema_migrations
    first_call_sql = conn.execute.call_args_list[0].args[0]
    assert "CREATE TABLE IF NOT EXISTS schema_migrations" in first_call_sql


@pytest.mark.asyncio
async def test_applies_new_migration_and_inserts_tracking_row():
    """A migration file not yet in schema_migrations is executed and tracked."""
    pool, conn = make_mock_pool(applied_filenames=[])
    db = Database()
    db.pool = pool

    with tempfile.TemporaryDirectory() as tmpdir:
        write_sql_files(Path(tmpdir), {"001_init.sql": "CREATE TABLE bar (id SERIAL);"})
        await db.run_migrations(tmpdir)

    execute_calls = [c.args[0] for c in conn.execute.call_args_list]

    # Migration SQL was executed
    assert any("CREATE TABLE bar" in s for s in execute_calls)

    # Tracking INSERT was executed
    assert any("INSERT INTO schema_migrations" in s for s in execute_calls)


@pytest.mark.asyncio
async def test_skips_already_applied_migration():
    """Files already in schema_migrations are not re-executed."""
    pool, conn = make_mock_pool(applied_filenames=["001_init.sql"])
    db = Database()
    db.pool = pool

    with tempfile.TemporaryDirectory() as tmpdir:
        write_sql_files(Path(tmpdir), {"001_init.sql": "CREATE TABLE bar (id SERIAL);"})
        await db.run_migrations(tmpdir)

    execute_calls = [c.args[0] for c in conn.execute.call_args_list]

    # Migration SQL must NOT be executed again
    assert not any("CREATE TABLE bar" in s for s in execute_calls)
    # Tracking INSERT must NOT be called again for this file
    assert not any("INSERT INTO schema_migrations" in s for s in execute_calls)


@pytest.mark.asyncio
async def test_applies_only_unapplied_migrations():
    """Only the unapplied file is executed when one of two files is already tracked."""
    pool, conn = make_mock_pool(applied_filenames=["001_init.sql"])
    db = Database()
    db.pool = pool

    with tempfile.TemporaryDirectory() as tmpdir:
        write_sql_files(Path(tmpdir), {
            "001_init.sql": "CREATE TABLE already_done (id SERIAL);",
            "002_new.sql": "CREATE TABLE new_table (id SERIAL);",
        })
        await db.run_migrations(tmpdir)

    execute_calls = [c.args[0] for c in conn.execute.call_args_list]

    assert not any("CREATE TABLE already_done" in s for s in execute_calls)
    assert any("CREATE TABLE new_table" in s for s in execute_calls)


@pytest.mark.asyncio
async def test_migration_error_raises_and_rolls_back():
    """A failing migration should propagate the exception so startup is halted."""
    pool, conn = make_mock_pool(applied_filenames=[])
    db = Database()
    db.pool = pool

    # Make the transaction context manager raise on __aexit__ (simulating rollback)
    # But more directly: make execute raise when it sees the migration SQL
    original_execute = conn.execute.side_effect

    async def failing_execute(sql, *args):
        if "BROKEN" in sql:
            raise Exception("syntax error")
        return "OK"

    conn.execute.side_effect = failing_execute

    with tempfile.TemporaryDirectory() as tmpdir:
        write_sql_files(Path(tmpdir), {"001_broken.sql": "BROKEN SQL;"})
        with pytest.raises(Exception, match="syntax error"):
            await db.run_migrations(tmpdir)


@pytest.mark.asyncio
async def test_no_migrations_dir_returns_silently():
    """If the migrations directory does not exist, function returns without error."""
    pool, conn = make_mock_pool()
    db = Database()
    db.pool = pool

    await db.run_migrations("/nonexistent/path/that/does/not/exist")

    # Pool should never be touched since directory doesn't exist
    pool.acquire.assert_not_called()


@pytest.mark.asyncio
async def test_raises_if_not_connected():
    """run_migrations raises RuntimeError when pool is not initialised."""
    db = Database()
    db.pool = None

    with pytest.raises(RuntimeError, match="Database not connected"):
        await db.run_migrations("/any/path")


@pytest.mark.asyncio
async def test_migrations_applied_in_sorted_order():
    """Files are applied in lexicographic (sorted) order regardless of OS listing."""
    pool, conn = make_mock_pool(applied_filenames=[])
    db = Database()
    db.pool = pool

    applied_order = []

    async def tracking_execute(sql, *args):
        if "INSERT INTO schema_migrations" in sql:
            applied_order.append(args[0])
        return "OK"

    conn.execute.side_effect = tracking_execute

    with tempfile.TemporaryDirectory() as tmpdir:
        write_sql_files(Path(tmpdir), {
            "003_c.sql": "SELECT 3;",
            "001_a.sql": "SELECT 1;",
            "002_b.sql": "SELECT 2;",
        })
        await db.run_migrations(tmpdir)

    assert applied_order == ["001_a.sql", "002_b.sql", "003_c.sql"]


# ---------------------------------------------------------------------------
# Property-Based Tests
# ---------------------------------------------------------------------------

from hypothesis import given, settings
from hypothesis import strategies as st


# Feature: optimization, Property 2: Migration idempotence
# Validates: Requirements 2
@given(
    filenames=st.lists(
        st.text(
            alphabet="abcdefghijklmnopqrstuvwxyz0123456789_",
            min_size=1,
            max_size=20,
        ).map(lambda s: s + ".sql"),
        min_size=1,
        max_size=5,
        unique=True,
    )
)
@settings(max_examples=50)
@pytest.mark.asyncio
async def test_migration_idempotence_property(filenames):
    """Property 2: Running run_migrations twice applies no additional SQL on the second run.

    **Validates: Requirements 2**
    """
    pool, conn = make_mock_pool(applied_filenames=[])
    db = Database()
    db.pool = pool

    executed_sqls: list[str] = []

    async def tracking_execute(sql, *args):
        executed_sqls.append(sql)
        return "OK"

    conn.execute.side_effect = tracking_execute

    with tempfile.TemporaryDirectory() as tmpdir:
        write_sql_files(Path(tmpdir), {f: f"SELECT 1; -- {f}" for f in filenames})
        await db.run_migrations(tmpdir)

        # Second run: all files are now "applied"
        pool2, conn2 = make_mock_pool(applied_filenames=filenames)
        db.pool = pool2
        executed_sqls2: list[str] = []

        async def tracking_execute2(sql, *args):
            executed_sqls2.append(sql)
            return "OK"

        conn2.execute.side_effect = tracking_execute2
        await db.run_migrations(tmpdir)

    # Second run should execute no migration-body SQL (only schema management calls)
    migration_sqls2 = [s for s in executed_sqls2 if "SELECT 1;" in s]
    assert len(migration_sqls2) == 0, (
        f"Second run executed migration SQL unexpectedly: {migration_sqls2}"
    )


# Feature: optimization, Property 3: Migration tracking round-trip
# Validates: Requirements 3
@pytest.mark.asyncio
async def test_migration_tracking_round_trip():
    """Property 3: After successful apply, filename appears in schema_migrations INSERT.

    **Validates: Requirements 3**
    """
    pool, conn = make_mock_pool(applied_filenames=[])
    db = Database()
    db.pool = pool

    tracked: list[str] = []

    async def tracking_execute(sql, *args):
        if "INSERT INTO schema_migrations" in sql:
            tracked.append(args[0])
        return "OK"

    conn.execute.side_effect = tracking_execute

    with tempfile.TemporaryDirectory() as tmpdir:
        write_sql_files(Path(tmpdir), {"001_round_trip.sql": "SELECT 1;"})
        await db.run_migrations(tmpdir)

    assert "001_round_trip.sql" in tracked, (
        f"Expected '001_round_trip.sql' in tracked inserts, got: {tracked}"
    )
