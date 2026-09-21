from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone

from .database import DatabaseConnection


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


BASE_SCHEMA = """
CREATE TABLE IF NOT EXISTS videos (
    video_id TEXT PRIMARY KEY,
    channel_id TEXT NOT NULL,
    title TEXT NOT NULL,
    published_at TEXT NOT NULL,
    content_type TEXT NOT NULL,
    live_status TEXT NOT NULL DEFAULT 'none',
    duration_seconds INTEGER NOT NULL DEFAULT 0,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_videos_channel_type
ON videos(channel_id, content_type, published_at);

CREATE TABLE IF NOT EXISTS video_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    age_hours REAL NOT NULL,
    views INTEGER NOT NULL,
    likes INTEGER NOT NULL,
    comments INTEGER NOT NULL,
    subscribers INTEGER,
    FOREIGN KEY(video_id) REFERENCES videos(video_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_snapshots_video_time
ON video_snapshots(video_id, observed_at);

CREATE INDEX IF NOT EXISTS idx_snapshots_video_age
ON video_snapshots(video_id, age_hours);

CREATE TABLE IF NOT EXISTS video_analyses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    topic TEXT NOT NULL DEFAULT '',
    opportunity INTEGER,
    outlier REAL,
    baseline INTEGER,
    baseline_method TEXT NOT NULL DEFAULT '',
    baseline_sample_size INTEGER NOT NULL DEFAULT 0,
    views_day REAL NOT NULL DEFAULT 0,
    engagement REAL NOT NULL DEFAULT 0,
    views_sub REAL,
    FOREIGN KEY(video_id) REFERENCES videos(video_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_analyses_video_time
ON video_analyses(video_id, observed_at);

CREATE INDEX IF NOT EXISTS idx_analyses_topic
ON video_analyses(topic, observed_at);

CREATE TABLE IF NOT EXISTS saved_research (
    video_id TEXT PRIMARY KEY,
    saved_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    why_saved TEXT NOT NULL DEFAULT '',
    adaptation TEXT NOT NULL DEFAULT '',
    unique_angle TEXT NOT NULL DEFAULT '',
    collection_name TEXT NOT NULL DEFAULT 'General',
    FOREIGN KEY(video_id) REFERENCES videos(video_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS ideas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_video_id TEXT,
    title TEXT NOT NULL,
    hook TEXT NOT NULL DEFAULT '',
    topic TEXT NOT NULL DEFAULT '',
    content_type TEXT NOT NULL DEFAULT 'Long-form',
    angle TEXT NOT NULL DEFAULT '',
    audience TEXT NOT NULL DEFAULT '',
    hypothesis TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    priority TEXT NOT NULL DEFAULT 'Med',
    status TEXT NOT NULL DEFAULT 'Draft',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(source_video_id) REFERENCES videos(video_id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_ideas_status
ON ideas(status, updated_at);

CREATE TABLE IF NOT EXISTS idea_documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    idea_id INTEGER NOT NULL,
    kind TEXT NOT NULL DEFAULT 'other',
    filename TEXT NOT NULL,
    content_type TEXT NOT NULL DEFAULT 'application/octet-stream',
    size_bytes INTEGER NOT NULL DEFAULT 0,
    content BLOB NOT NULL,
    uploaded_at TEXT NOT NULL,
    cloud_provider TEXT NOT NULL DEFAULT '',
    cloud_file_id TEXT NOT NULL DEFAULT '',
    cloud_url TEXT NOT NULL DEFAULT '',
    cloud_uploaded_at TEXT,
    FOREIGN KEY(idea_id) REFERENCES ideas(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_idea_documents_idea
ON idea_documents(idea_id, uploaded_at);

CREATE TABLE IF NOT EXISTS experiments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    idea_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    topic TEXT NOT NULL DEFAULT '',
    format TEXT NOT NULL DEFAULT 'Long-form',
    hypothesis TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'Draft',
    published_at TEXT,
    views_24h INTEGER,
    views_7d INTEGER,
    retention REAL,
    subscribers INTEGER,
    ctr REAL,
    result TEXT NOT NULL DEFAULT '',
    decision TEXT NOT NULL DEFAULT 'UNDECIDED',
    lesson TEXT NOT NULL DEFAULT '',
    next_test TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(idea_id) REFERENCES ideas(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_experiments_idea
ON experiments(idea_id, updated_at);

CREATE INDEX IF NOT EXISTS idx_experiments_decision
ON experiments(decision, updated_at);
"""


def _migration_1_base_schema(db: DatabaseConnection) -> None:
    db.executescript(BASE_SCHEMA)


def _migration_2_video_metadata(db: DatabaseConnection) -> None:
    columns = db.columns("videos")
    if "channel_title" not in columns:
        db.execute("ALTER TABLE videos ADD COLUMN channel_title TEXT NOT NULL DEFAULT ''")
    if "thumbnail" not in columns:
        db.execute("ALTER TABLE videos ADD COLUMN thumbnail TEXT")
    if "youtube_url" not in columns:
        db.execute("ALTER TABLE videos ADD COLUMN youtube_url TEXT")


def _migration_3_document_cloud_metadata(db: DatabaseConnection) -> None:
    columns = db.columns("idea_documents")
    if "cloud_provider" not in columns:
        db.execute("ALTER TABLE idea_documents ADD COLUMN cloud_provider TEXT NOT NULL DEFAULT ''")
    if "cloud_file_id" not in columns:
        db.execute("ALTER TABLE idea_documents ADD COLUMN cloud_file_id TEXT NOT NULL DEFAULT ''")
    if "cloud_url" not in columns:
        db.execute("ALTER TABLE idea_documents ADD COLUMN cloud_url TEXT NOT NULL DEFAULT ''")
    if "cloud_uploaded_at" not in columns:
        db.execute("ALTER TABLE idea_documents ADD COLUMN cloud_uploaded_at TEXT")


MIGRATIONS: tuple[tuple[int, str, Callable[[DatabaseConnection], None]], ...] = (
    (1, "base_schema", _migration_1_base_schema),
    (2, "video_metadata", _migration_2_video_metadata),
    (3, "document_cloud_metadata", _migration_3_document_cloud_metadata),
)


def run_migrations(connect: Callable[[], DatabaseConnection]) -> None:
    """Apply idempotent schema migrations to SQLite or PostgreSQL.

    Legacy SQLite databases did not have schema_migrations. Migration 1 uses
    CREATE IF NOT EXISTS, while later migrations inspect columns before ALTER,
    so existing databases can be adopted safely.
    """
    with connect() as db:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at TEXT NOT NULL
            )
            """
        )
        applied = {
            int(row["version"])
            for row in db.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            ).fetchall()
        }

        for version, name, migration in MIGRATIONS:
            if version in applied:
                continue
            migration(db)
            db.execute(
                """
                INSERT INTO schema_migrations (version, name, applied_at)
                VALUES (?, ?, ?)
                """,
                (version, name, _now_iso()),
            )
