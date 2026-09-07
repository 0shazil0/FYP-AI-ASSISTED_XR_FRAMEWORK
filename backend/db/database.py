"""
backend/db/database.py
=======================
Async SQLite connection manager for the NeuroGuide XR lesson pipeline.

USES: aiosqlite — async wrapper around sqlite3 (no blocking I/O on the event loop).

USAGE:
    from db.database import get_db, init_db

    # In FastAPI lifespan:
    await init_db()

    # In a route or service:
    async with get_db() as db:
        rows = await db.execute_fetchall("SELECT * FROM lessons WHERE org_id=?", (org_id,))

DESIGN:
    • DB file path is controlled by DB_PATH in .env (default: neuroguide.db next to backend/).
    • init_db() runs schema.sql — safe to call on every startup (CREATE TABLE IF NOT EXISTS).
    • get_db() yields an aiosqlite.Connection with row_factory set to sqlite3.Row
      so rows are accessible as both index and name (row["title"]).
    • All queries use parameterised ? placeholders — never f-strings for user data.
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

import aiosqlite

# ── DB path ───────────────────────────────────────────────────────────────────
# Default: neuroguide.db in the backend/ directory.
# Override by setting DB_PATH in backend/.env.
_DB_PATH = os.getenv("DB_PATH", str(Path(__file__).parent.parent / "neuroguide.db"))

# ── Schema file ───────────────────────────────────────────────────────────────
_SCHEMA_PATH = Path(__file__).parent / "schema.sql"


async def init_db() -> None:
    """
    Run schema.sql against the SQLite database.
    Safe to call on every startup — all statements use CREATE TABLE IF NOT EXISTS.
    """
    if not _SCHEMA_PATH.exists():
        raise FileNotFoundError(f"[DB] schema.sql not found at {_SCHEMA_PATH}")

    schema_sql = _SCHEMA_PATH.read_text(encoding="utf-8")

    async with aiosqlite.connect(_DB_PATH) as db:
        db.row_factory = sqlite3.Row
        await db.executescript(schema_sql)
        await db.commit()

    print(f"[DB] Schema applied. DB at: {_DB_PATH}")


@asynccontextmanager
async def get_db() -> AsyncIterator[aiosqlite.Connection]:
    """
    Async context manager that yields a configured aiosqlite Connection.

    Usage:
        async with get_db() as db:
            await db.execute("INSERT INTO lessons ...", (...))
            await db.commit()
    """
    async with aiosqlite.connect(_DB_PATH) as db:
        db.row_factory = sqlite3.Row
        # Enable foreign key enforcement per connection (SQLite default is off)
        await db.execute("PRAGMA foreign_keys = ON")
        yield db


async def fetchall(
    query: str,
    params: tuple = ()
) -> list[sqlite3.Row]:
    """
    Run a SELECT and return all rows.

    Args:
        query:  SQL SELECT statement with ? placeholders.
        params: Tuple of parameter values.

    Returns:
        List of sqlite3.Row objects (accessible by column name).
    """
    async with get_db() as db:
        cursor = await db.execute(query, params)
        return await cursor.fetchall()


async def fetchone(
    query: str,
    params: tuple = ()
) -> sqlite3.Row | None:
    """Run a SELECT and return the first row, or None."""
    async with get_db() as db:
        cursor = await db.execute(query, params)
        return await cursor.fetchone()


async def execute(
    query: str,
    params: tuple = ()
) -> int:
    """
    Run an INSERT / UPDATE / DELETE and return the lastrowid (for INSERT).

    Returns:
        lastrowid for INSERT, 0 for UPDATE/DELETE.
    """
    async with get_db() as db:
        cursor = await db.execute(query, params)
        await db.commit()
        return cursor.lastrowid or 0
