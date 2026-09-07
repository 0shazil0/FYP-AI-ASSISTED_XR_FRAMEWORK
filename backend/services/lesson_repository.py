"""
backend/services/lesson_repository.py
======================================
Async CRUD layer for the NeuroGuide XR lesson pipeline.

Wraps the aiosqlite-backed ``db.database`` helpers so all callers
(demo_ingestor, lesson WebSocket endpoint, admin_api) can work through
a clean, type-annotated interface rather than raw SQL.

TABLES USED:
  organizations  - companies / institutions
  lessons        - one row per workflow
  steps          - normalised step records (with template_path)
  templates      - deduplicated visual template library
  lesson_assignments - trainer assigns lesson to learner
  lesson_sessions    - one row per learner-lesson run
  step_events        - fine-grained action log per step

DESIGN:
  - All methods are async-compatible (uses aiosqlite via db.get_db()).
  - IDs are SQLite auto-increment integers; returned as int.
  - Rows returned as plain dicts (converted from sqlite3.Row for JSON compat).
  - No ORM dependency -- keeps the stack minimal for the FYP.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from db.database import get_db, fetchall, fetchone, execute


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _row_to_dict(row) -> dict:
    """Convert a sqlite3.Row (or None) to a plain dict."""
    if row is None:
        return {}
    return dict(row)


def _rows_to_list(rows) -> list[dict]:
    return [dict(r) for r in (rows or [])]


# ---------------------------------------------------------------------------
# Organization helpers (lightweight -- usually pre-seeded)
# ---------------------------------------------------------------------------

async def get_or_create_org(name: str) -> int:
    """Return org id, creating it if absent."""
    row = await fetchone("SELECT id FROM organizations WHERE name=?", (name,))
    if row:
        return row["id"]
    return await execute(
        "INSERT OR IGNORE INTO organizations (name) VALUES (?)", (name,)
    )


# ---------------------------------------------------------------------------
# User helpers
# ---------------------------------------------------------------------------

async def get_or_create_user(
    email: str,
    display_name: str,
    org_id: int,
    role: str = "learner",
    password_hash: str = "",
) -> int:
    """Return user id, creating a stub record if absent."""
    row = await fetchone("SELECT id FROM users WHERE email=?", (email,))
    if row:
        return row["id"]
    return await execute(
        "INSERT INTO users (org_id, email, display_name, role, password_hash) "
        "VALUES (?,?,?,?,?)",
        (org_id, email, display_name, role, password_hash),
    )


async def get_user(user_id: int) -> dict:
    row = await fetchone("SELECT * FROM users WHERE id=?", (user_id,))
    return _row_to_dict(row)


# ---------------------------------------------------------------------------
# Lesson CRUD
# ---------------------------------------------------------------------------

async def create_lesson(
    title: str,
    app_name: str,
    org_id: int,
    created_by: int,
    description: str = "",
    source_type: str = "openadapt",
    source_path: Optional[str] = None,
) -> int:
    """Insert a new lesson row and return its id."""
    return await execute(
        "INSERT INTO lessons "
        "  (org_id, created_by, title, description, app_name, source_type, source_path) "
        "VALUES (?,?,?,?,?,?,?)",
        (org_id, created_by, title, description, app_name, source_type, source_path),
    )


async def get_lesson(lesson_id: int) -> dict:
    row = await fetchone("SELECT * FROM lessons WHERE id=?", (lesson_id,))
    return _row_to_dict(row)


async def list_lessons(org_id: Optional[int] = None, status: Optional[str] = None) -> list[dict]:
    parts = ["SELECT * FROM lessons WHERE 1=1"]
    params: list = []
    if org_id is not None:
        parts.append("AND org_id=?"); params.append(org_id)
    if status:
        parts.append("AND status=?"); params.append(status)
    parts.append("ORDER BY created_at DESC")
    rows = await fetchall(" ".join(parts), tuple(params))
    return _rows_to_list(rows)


async def publish_lesson(lesson_id: int) -> None:
    await execute(
        "UPDATE lessons SET status='published', updated_at=strftime('%Y-%m-%dT%H:%M:%SZ','now') "
        "WHERE id=?",
        (lesson_id,),
    )


async def update_lesson_steps_json(lesson_id: int, steps: list[dict]) -> None:
    """Update the denormalised steps_json cache on the lesson row."""
    await execute(
        "UPDATE lessons SET steps_json=?, updated_at=strftime('%Y-%m-%dT%H:%M:%SZ','now') "
        "WHERE id=?",
        (json.dumps(steps), lesson_id),
    )


# ---------------------------------------------------------------------------
# Step CRUD
# ---------------------------------------------------------------------------

async def upsert_steps(lesson_id: int, steps: list[dict]) -> list[int]:
    """
    Insert-or-replace all steps for a lesson.
    Returns list of inserted step ids (same order as input).

    Each step dict may contain:
      step_index, action, target, target_type, value, tts_text,
      template_path, bbox_x1, bbox_y1, bbox_x2, bbox_y2, expected_screenshot
    """
    # Clear existing steps for this lesson first (full replace)
    await execute("DELETE FROM steps WHERE lesson_id=?", (lesson_id,))

    ids: list[int] = []
    for s in steps:
        row_id = await execute(
            "INSERT INTO steps "
            "  (lesson_id, step_index, action, target, target_type, value, "
            "   tts_text, template_path, bbox_x1, bbox_y1, bbox_x2, bbox_y2, "
            "   expected_screenshot) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                lesson_id,
                s.get("step_index", 0),
                s.get("action", "click"),
                s.get("target", ""),
                s.get("target_type", "Button"),
                s.get("value", ""),
                s.get("tts_text", ""),
                s.get("template_path"),
                s.get("bbox_x1"),
                s.get("bbox_y1"),
                s.get("bbox_x2"),
                s.get("bbox_y2"),
                s.get("expected_screenshot"),
            ),
        )
        ids.append(row_id)

    # Refresh cached steps_json on the lesson row
    await update_lesson_steps_json(lesson_id, steps)
    return ids


async def get_steps(lesson_id: int) -> list[dict]:
    """Return all steps for a lesson ordered by step_index."""
    rows = await fetchall(
        "SELECT * FROM steps WHERE lesson_id=? ORDER BY step_index", (lesson_id,)
    )
    return _rows_to_list(rows)


async def get_step(step_id: int) -> dict:
    row = await fetchone("SELECT * FROM steps WHERE id=?", (step_id,))
    return _row_to_dict(row)


async def update_step(step_id: int, fields: dict[str, Any]) -> None:
    """Partial update for a single step (e.g. after admin edits tts_text)."""
    allowed = {
        "action", "target", "target_type", "value", "tts_text",
        "template_path", "bbox_x1", "bbox_y1", "bbox_x2", "bbox_y2",
    }
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return
    set_clause = ", ".join(f"{k}=?" for k in updates)
    await execute(
        f"UPDATE steps SET {set_clause} WHERE id=?",
        (*updates.values(), step_id),
    )


# ---------------------------------------------------------------------------
# Template library CRUD
# ---------------------------------------------------------------------------

async def save_template(
    app_name: str,
    label: str,
    file_path: str,
    step_id: Optional[int] = None,
) -> None:
    """
    Insert or replace a template record.
    UNIQUE(app_name, label) ensures deduplication -- updating file_path if it changes.
    """
    await execute(
        "INSERT INTO templates (app_name, label, file_path, created_from_step) "
        "VALUES (?,?,?,?) "
        "ON CONFLICT(app_name, label) DO UPDATE SET file_path=excluded.file_path",
        (app_name, label, file_path, step_id),
    )


async def get_template(app_name: str, label: str) -> Optional[str]:
    """
    Return the file_path for a template matching (app_name, label), or None.
    Used by the runtime resolution chain as the fast visual fallback.
    """
    row = await fetchone(
        "SELECT file_path FROM templates WHERE app_name=? AND label=?",
        (app_name, label),
    )
    return row["file_path"] if row else None


async def list_templates(app_name: Optional[str] = None) -> list[dict]:
    if app_name:
        rows = await fetchall(
            "SELECT * FROM templates WHERE app_name=? ORDER BY label", (app_name,)
        )
    else:
        rows = await fetchall("SELECT * FROM templates ORDER BY app_name, label")
    return _rows_to_list(rows)


# ---------------------------------------------------------------------------
# Assignments
# ---------------------------------------------------------------------------

async def assign_lesson(
    lesson_id: int, learner_id: int, assigned_by: int, due_at: Optional[str] = None
) -> int:
    return await execute(
        "INSERT OR IGNORE INTO lesson_assignments "
        "  (lesson_id, learner_id, assigned_by, due_at) VALUES (?,?,?,?)",
        (lesson_id, learner_id, assigned_by, due_at),
    )


async def get_assignments_for_learner(learner_id: int) -> list[dict]:
    rows = await fetchall(
        "SELECT la.*, l.title, l.app_name, l.status "
        "FROM lesson_assignments la "
        "JOIN lessons l ON l.id = la.lesson_id "
        "WHERE la.learner_id=? ORDER BY la.created_at DESC",
        (learner_id,),
    )
    return _rows_to_list(rows)


# ---------------------------------------------------------------------------
# Sessions & progress
# ---------------------------------------------------------------------------

async def start_session(lesson_id: int, learner_id: int) -> int:
    """Create a new lesson session and return its id."""
    return await execute(
        "INSERT INTO lesson_sessions (lesson_id, learner_id) VALUES (?,?)",
        (lesson_id, learner_id),
    )


async def update_session_step(session_id: int, current_step: int) -> None:
    await execute(
        "UPDATE lesson_sessions SET current_step=? WHERE id=?",
        (current_step, session_id),
    )


async def complete_session(session_id: int, score: Optional[float] = None) -> None:
    await execute(
        "UPDATE lesson_sessions "
        "SET status='completed', completed_at=strftime('%Y-%m-%dT%H:%M:%SZ','now'), score=? "
        "WHERE id=?",
        (score, session_id),
    )


async def get_session(session_id: int) -> dict:
    row = await fetchone("SELECT * FROM lesson_sessions WHERE id=?", (session_id,))
    return _row_to_dict(row)


async def get_progress(lesson_id: int, learner_id: int) -> list[dict]:
    """Return all sessions for a learner on a lesson, newest first."""
    rows = await fetchall(
        "SELECT * FROM lesson_sessions "
        "WHERE lesson_id=? AND learner_id=? ORDER BY started_at DESC",
        (lesson_id, learner_id),
    )
    return _rows_to_list(rows)


async def log_step_event(
    session_id: int,
    step_id: int,
    event_type: str,
    diff_score: Optional[float] = None,
    tts_text: Optional[str] = None,
) -> None:
    """Record a fine-grained learner action (shown, done_tapped, verified_pass, etc.)."""
    await execute(
        "INSERT INTO step_events (session_id, step_id, event_type, diff_score, tts_text) "
        "VALUES (?,?,?,?,?)",
        (session_id, step_id, event_type, diff_score, tts_text),
    )
