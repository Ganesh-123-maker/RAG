"""SQLite multi-process contention.

The API server and the ingestion worker are two processes sharing one
SQLite file. With the stock settings, a write that arrives while the
other process holds the write lock fails after the 5s default timeout
with ``sqlite3.OperationalError: database is locked``. That is exactly
what killed the streamed-chat persist in a live browser run
(2026-11-12): the assistant answer was generated and cited correctly,
then its INSERT rolled back and the UI showed nothing.

The fix (app/core/database.py): WAL journal mode + 30s busy timeout.
This test holds an exclusive write lock for 7s — longer than the old
5s default — and requires a write through the app's own session
factory to wait it out and succeed.
"""

from __future__ import annotations

import asyncio
import importlib
import sqlite3
import time
import uuid

import pytest
from sqlalchemy import select

import app.core.config as config_module
import app.core.database as db_module
from app.models.user import User

pytestmark = pytest.mark.asyncio


async def test_write_waits_out_lock_longer_than_old_default(tmp_path, monkeypatch):
    db_file = tmp_path / "contention.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_file}")
    # Reloading database.py rebuilds the engine from the tmp file —
    # but it also creates a fresh Base, while the mapped models stay
    # registered on the original one (and a previous reload in this
    # process may already have replaced db_module.Base with an empty
    # one). Take the metadata from a mapped model instead, so
    # create_all always sees every table.
    tables = User.__table__.metadata
    config_module.get_settings.cache_clear()
    importlib.reload(db_module)
    try:
        async with db_module.engine.begin() as conn:
            await conn.run_sync(tables.create_all)

        # WAL is actually on for this file.
        raw = sqlite3.connect(db_file)
        assert raw.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        raw.close()

        def hold_lock() -> None:
            conn = sqlite3.connect(db_file, timeout=5)
            try:
                conn.execute("BEGIN IMMEDIATE")
                # Include every NOT NULL column without a server
                # default (failed_login_attempts is a Python-side
                # default only) — otherwise the INSERT raises and the
                # traceback keeps the connection (and its lock) alive.
                conn.execute(
                    "INSERT INTO users (id, email, hashed_password, full_name,"
                    " is_active, failed_login_attempts)"
                    " VALUES (?, ?, ?, ?, ?, ?)",
                    (str(uuid.uuid4()), "locker@example.com", "x", "Locker", 1, 0),
                )
                time.sleep(7)
                conn.commit()
            finally:
                conn.close()

        holder = asyncio.create_task(asyncio.to_thread(hold_lock))
        await asyncio.sleep(0.5)  # let the holder take the lock first

        # Before the fix this raised OperationalError after ~5s; with
        # the 30s busy timeout it waits out the 7s hold and commits.
        async with db_module.AsyncSessionLocal() as session:
            session.add(
                User(
                    id=uuid.uuid4(),
                    email="writer@example.com",
                    hashed_password="x",
                    full_name="Writer",
                    is_active=True,
                )
            )
            await session.commit()

        await holder

        async with db_module.AsyncSessionLocal() as session:
            emails = (await session.execute(select(User.email))).scalars().all()
        assert "writer@example.com" in emails
        assert "locker@example.com" in emails
    finally:
        await db_module.engine.dispose()
        config_module.get_settings.cache_clear()
        importlib.reload(db_module)
