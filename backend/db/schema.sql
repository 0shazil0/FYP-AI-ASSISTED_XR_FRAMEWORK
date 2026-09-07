-- backend/db/schema.sql
-- NeuroGuide XR SQLite Schema  v2.0
-- ==================================
-- Covers the full lesson pipeline:
--   organizations → users → lessons → steps → templates
--                → lesson_sessions → step_events
--
-- v2.0 additions:
--   • steps.template_path  — path to auto-extracted 96×96 template PNG
--   • templates table      — deduplicated visual library (app_name, label)
--
-- Run once at startup via:
--   python -c "from db.database import init_db; import asyncio; asyncio.run(init_db())"
-- Or automatically via backend/main.py lifespan event.
--
-- NOTES:
--   • All timestamps are ISO-8601 UTC strings (SQLite has no native datetime type).
--   • step_events is the learner's action log — used for analytics + adaptive guidance.
--   • lesson_sessions link a learner to one active run through a lesson.

PRAGMA journal_mode=WAL;   -- Write-Ahead Logging for concurrent reads
PRAGMA foreign_keys=ON;

-- ─────────────────────────────────────────────────────────────────────────────
-- ORGANIZATIONS
-- A company or institution that owns lessons and users.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS organizations (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL UNIQUE,
    created_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

-- ─────────────────────────────────────────────────────────────────────────────
-- USERS
-- Trainers (role='trainer') upload lessons.
-- Learners (role='learner') complete lessons.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS users (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    org_id          INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    email           TEXT    NOT NULL UNIQUE,
    display_name    TEXT    NOT NULL,
    role            TEXT    NOT NULL DEFAULT 'learner'   CHECK(role IN ('admin','trainer','learner')),
    password_hash   TEXT    NOT NULL,
    created_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_users_org ON users(org_id);

-- ─────────────────────────────────────────────────────────────────────────────
-- LESSONS
-- A lesson is a single guided workflow (e.g. "Create a Pivot Table in Excel").
-- The 'steps_json' column stores the raw LLM-generated step list (denormalised
-- for fast retrieval). Canonical step records are in the 'steps' table.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS lessons (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    org_id          INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    created_by      INTEGER NOT NULL REFERENCES users(id),
    title           TEXT    NOT NULL,
    description     TEXT    NOT NULL DEFAULT '',
    app_name        TEXT    NOT NULL DEFAULT 'Word',   -- target application
    status          TEXT    NOT NULL DEFAULT 'draft'   CHECK(status IN ('draft','published','archived')),
    -- Raw recording source: 'video_upload' | 'openadapt' | 'manual'
    source_type     TEXT    NOT NULL DEFAULT 'manual',
    source_path     TEXT,                              -- path to uploaded video or OA session file
    -- Ingestor output: normalised steps as JSON array (cache for fast delivery)
    steps_json      TEXT    NOT NULL DEFAULT '[]',
    created_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_lessons_org    ON lessons(org_id);
CREATE INDEX IF NOT EXISTS idx_lessons_status ON lessons(status);

-- ─────────────────────────────────────────────────────────────────────────────
-- STEPS
-- Normalised step records extracted from the lesson ingestor.
-- Each step maps to one LLM-generated action in the lesson.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS steps (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    lesson_id       INTEGER NOT NULL REFERENCES lessons(id) ON DELETE CASCADE,
    step_index      INTEGER NOT NULL,          -- 0-based order within lesson
    action          TEXT    NOT NULL,          -- 'click' | 'type' | 'scroll' | etc.
    target          TEXT    NOT NULL,          -- UI element label
    target_type     TEXT    NOT NULL DEFAULT 'Button', -- Button | MenuItem | Edit | TabItem | Icon
    value           TEXT    NOT NULL DEFAULT '', -- text to type (for 'type' actions)
    tts_text        TEXT    NOT NULL DEFAULT '', -- coaching sentence for TTS
    -- Auto-extracted visual template (96×96 px PNG cropped from trainer recording)
    -- Used at runtime: pywinauto (5ms) → template match (15ms) → OmniParser (350ms)
    template_path   TEXT,                      -- e.g. "templates/winword/shapes_button.png"
    -- OmniParser / pywinauto resolved bounding box (normalised 0–1, may be NULL)
    bbox_x1         REAL,
    bbox_y1         REAL,
    bbox_x2         REAL,
    bbox_y2         REAL,
    -- Screenshot of the expected screen state after this step (base64 JPEG thumbnail)
    expected_screenshot TEXT,
    created_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_steps_lesson ON steps(lesson_id, step_index);

-- ─────────────────────────────────────────────────────────────────────────────
-- TEMPLATES
-- Deduplicated visual library of auto-extracted UI element templates.
-- Every time a trainer records a demo, demo_ingestor.py crops a 96×96 patch
-- around each click and saves it here.
-- At runtime the resolution chain checks this table before falling back to OmniParser.
-- UNIQUE(app_name, label) ensures one canonical template per element per application.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS templates (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    app_name        TEXT    NOT NULL,   -- process name, e.g. 'WINWORD.EXE'
    label           TEXT    NOT NULL,   -- UI element label, e.g. 'Shapes button'
    file_path       TEXT    NOT NULL,   -- relative path to PNG, e.g. 'templates/winword/shapes_button.png'
    created_from_step INTEGER REFERENCES steps(id) ON DELETE SET NULL,
    created_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    UNIQUE(app_name, label)             -- deduplication: one template per (app, label)
);

CREATE INDEX IF NOT EXISTS idx_templates_app ON templates(app_name);

-- ─────────────────────────────────────────────────────────────────────────────
-- LESSON ASSIGNMENTS
-- A trainer assigns a lesson to a learner (or a group of learners).
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS lesson_assignments (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    lesson_id       INTEGER NOT NULL REFERENCES lessons(id) ON DELETE CASCADE,
    learner_id      INTEGER NOT NULL REFERENCES users(id)   ON DELETE CASCADE,
    assigned_by     INTEGER NOT NULL REFERENCES users(id),
    due_at          TEXT,                      -- ISO-8601 deadline (nullable)
    created_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    UNIQUE(lesson_id, learner_id)
);

CREATE INDEX IF NOT EXISTS idx_assignments_learner ON lesson_assignments(learner_id);

-- ─────────────────────────────────────────────────────────────────────────────
-- LESSON SESSIONS
-- One row per learner-lesson run. Tracks overall progress.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS lesson_sessions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    lesson_id       INTEGER NOT NULL REFERENCES lessons(id) ON DELETE CASCADE,
    learner_id      INTEGER NOT NULL REFERENCES users(id)   ON DELETE CASCADE,
    status          TEXT    NOT NULL DEFAULT 'in_progress'
                            CHECK(status IN ('in_progress','completed','abandoned')),
    current_step    INTEGER NOT NULL DEFAULT 0,   -- last confirmed step index
    score           REAL,                         -- optional % score (0.0–100.0)
    started_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    completed_at    TEXT                           -- set when status='completed'
);

CREATE INDEX IF NOT EXISTS idx_sessions_learner ON lesson_sessions(learner_id);
CREATE INDEX IF NOT EXISTS idx_sessions_lesson  ON lesson_sessions(lesson_id);

-- ─────────────────────────────────────────────────────────────────────────────
-- STEP EVENTS
-- Fine-grained learner action log per session step.
-- Used for progress analytics, adaptive hints, and completion verification.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS step_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      INTEGER NOT NULL REFERENCES lesson_sessions(id) ON DELETE CASCADE,
    step_id         INTEGER NOT NULL REFERENCES steps(id),
    event_type      TEXT    NOT NULL,  -- 'shown' | 'done_tapped' | 'verified_pass' | 'verified_fail' | 'skipped'
    diff_score      REAL,              -- visual diff from VerificationService (0–1)
    tts_text        TEXT,              -- coaching text spoken at this event
    created_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_events_session ON step_events(session_id);
