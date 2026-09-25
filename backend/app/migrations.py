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


def _migration_4_prune_legacy_unsaved_research(db: DatabaseConnection) -> None:
    """One-time cleanup of prototype research history.

    The early VibeFlow/alpha workflow accumulated large amounts of temporary
    YouTube candidate and channel-history data while the product was being
    tested. Keep only research that the creator explicitly saved or that an
    Idea still references. Creator workflow rows (ideas, documents and
    experiments) are left untouched.

    Delete child rows explicitly so the cleanup behaves the same on SQLite and
    PostgreSQL even if foreign-key cascade settings differ.
    """

    workspace_saved_guard = ""
    if db.columns("workspace_saved_research"):
        workspace_saved_guard = """
        AND NOT EXISTS (
            SELECT 1
            FROM workspace_saved_research wsr
            WHERE wsr.video_id = v.video_id
        )
        """

    removable_video_ids = f"""
        SELECT v.video_id
        FROM videos v
        WHERE NOT EXISTS (
            SELECT 1
            FROM saved_research sr
            WHERE sr.video_id = v.video_id
        )
        {workspace_saved_guard}
        AND NOT EXISTS (
            SELECT 1
            FROM ideas i
            WHERE i.source_video_id = v.video_id
        )
    """

    db.execute(
        f"""
        DELETE FROM video_analyses
        WHERE video_id IN ({removable_video_ids})
        """
    )
    db.execute(
        f"""
        DELETE FROM video_snapshots
        WHERE video_id IN ({removable_video_ids})
        """
    )
    db.execute(
        f"""
        DELETE FROM videos
        WHERE video_id IN ({removable_video_ids})
        """
    )


def _migration_5_private_alpha_workspaces(db: DatabaseConnection) -> None:
    """Scope creator-owned workflow rows without duplicating the public research corpus.

    Existing creator data is assigned to the special owner workspace. Tester
    invite links use opaque workspace IDs, so saved research and workflow rows
    are isolated while public YouTube observations remain shared evidence.
    """

    db.execute(
        """
        CREATE TABLE IF NOT EXISTS workspace_access (
            workspace_id TEXT PRIMARY KEY,
            access_key_hash TEXT NOT NULL DEFAULT '',
            claimed_at TEXT
        )
        """
    )
    owner_access = db.execute(
        "SELECT workspace_id FROM workspace_access WHERE workspace_id = 'owner'"
    ).fetchone()
    if owner_access is None:
        db.execute(
            """
            INSERT INTO workspace_access (workspace_id, access_key_hash, claimed_at)
            VALUES ('owner', '', NULL)
            """
        )

    db.execute(
        """
        CREATE TABLE IF NOT EXISTS workspace_saved_research (
            workspace_id TEXT NOT NULL,
            video_id TEXT NOT NULL,
            saved_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            why_saved TEXT NOT NULL DEFAULT '',
            adaptation TEXT NOT NULL DEFAULT '',
            unique_angle TEXT NOT NULL DEFAULT '',
            collection_name TEXT NOT NULL DEFAULT 'General',
            PRIMARY KEY(workspace_id, video_id),
            FOREIGN KEY(video_id) REFERENCES videos(video_id) ON DELETE CASCADE
        )
        """
    )

    existing = db.execute(
        "SELECT COUNT(*) AS count FROM workspace_saved_research"
    ).fetchone()
    if int(existing["count"] or 0) == 0:
        db.execute(
            """
            INSERT INTO workspace_saved_research (
                workspace_id, video_id, saved_at, updated_at, why_saved,
                adaptation, unique_angle, collection_name
            )
            SELECT
                'owner', video_id, saved_at, updated_at, why_saved,
                adaptation, unique_angle, collection_name
            FROM saved_research
            """
        )

    idea_columns = db.columns("ideas")
    if "workspace_id" not in idea_columns:
        db.execute(
            "ALTER TABLE ideas ADD COLUMN workspace_id TEXT NOT NULL DEFAULT 'owner'"
        )

    db.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_workspace_saved_research_saved
        ON workspace_saved_research(workspace_id, saved_at)
        """
    )
    db.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_ideas_workspace_updated
        ON ideas(workspace_id, updated_at)
        """
    )


MIGRATIONS: tuple[tuple[int, str, Callable[[DatabaseConnection], None]], ...] = (
    (1, "base_schema", _migration_1_base_schema),
    (2, "video_metadata", _migration_2_video_metadata),
    (3, "document_cloud_metadata", _migration_3_document_cloud_metadata),
    (4, "prune_legacy_unsaved_research", _migration_4_prune_legacy_unsaved_research),
    (5, "private_alpha_workspaces", _migration_5_private_alpha_workspaces),
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
