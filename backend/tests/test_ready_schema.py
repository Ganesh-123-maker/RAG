"""Readiness must verify the schema, not just the connection.

A backend started before `alembic upgrade head` used to report
/ready while every request 500d (the worker crashed with "no such
table: documents" in Phase 1). _check_database now also requires
the alembic_version table, which only exists after migrations.
"""
from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

import app.main as main_module

pytestmark = pytest.mark.asyncio


async def test_ready_check_fails_without_migrations(tmp_path, monkeypatch) -> None:
    db_file = tmp_path / "nomig.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    monkeypatch.setattr(main_module, "engine", engine)
    try:
        with pytest.raises(Exception):
            await main_module._check_database()
        # After creating just the alembic_version table, the check passes.
        async with engine.begin() as conn:
            await conn.execute(
                text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
            )
        await main_module._check_database()
    finally:
        await engine.dispose()
