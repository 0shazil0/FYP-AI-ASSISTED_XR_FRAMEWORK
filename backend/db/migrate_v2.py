"""
backend/db/migrate_v2.py
========================
One-time migration: add target_type + template_path to steps,
create templates table. Safe to run multiple times (idempotent).

Usage:
    python db/migrate_v2.py
"""
import aiosqlite
import asyncio
import sqlite3
from pathlib import Path

DB_PATH = str(Path(__file__).parent.parent / "neuroguide.db")

CREATE_TEMPLATES = """
CREATE TABLE IF NOT EXISTS templates (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    app_name          TEXT    NOT NULL,
    label             TEXT    NOT NULL,
    file_path         TEXT    NOT NULL,
    created_from_step INTEGER REFERENCES steps(id) ON DELETE SET NULL,
    created_at        TEXT    NOT NULL DEFAULT (strftime('"'"'%Y-%m-%dT%H:%M:%SZ'"'"', '"'"'now'"'"')),
    UNIQUE(app_name, label)
);
CREATE INDEX IF NOT EXISTS idx_templates_app ON templates(app_name);
"""


async def migrate():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = sqlite3.Row
        await db.execute("PRAGMA foreign_keys=OFF")

        # Check existing columns in steps
        cur = await db.execute("PRAGMA table_info(steps)")
        cols = [r[1] for r in await cur.fetchall()]
        print("Existing steps columns:", cols)

        if "target_type" not in cols:
            await db.execute(
                "ALTER TABLE steps ADD COLUMN target_type TEXT NOT NULL DEFAULT " + chr(39) + "Button" + chr(39)
            )
            print("  + Added steps.target_type")

        if "template_path" not in cols:
            await db.execute("ALTER TABLE steps ADD COLUMN template_path TEXT")
            print("  + Added steps.template_path")

        # Check templates table
        cur2 = await db.execute(
            "SELECT name FROM sqlite_master WHERE type=" + chr(39) + "table" + chr(39) + " AND name=" + chr(39) + "templates" + chr(39)
        )
        if not await cur2.fetchone():
            await db.executescript(CREATE_TEMPLATES)
            print("  + Created templates table")
        else:
            print("  templates table already exists")

        await db.execute("PRAGMA foreign_keys=ON")
        await db.commit()
        print("Migration complete.")


if __name__ == "__main__":
    asyncio.run(migrate())
