"""SQLite connection + versioned SQL migration runner.

Ported from gongkao-learning-os and generalized: pure sqlite3, no ORM.
Migrations live in backend/migrations/NNN_*.sql and are applied in order,
recorded in schema_migrations. All data is scoped by pack_id.
"""
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS_DIR = Path(__file__).resolve().parent / 'migrations'


def default_path():
    return Path(os.environ.get('ANYLEARN_DB_PATH', ROOT / 'data' / 'anylearn.db'))


@contextmanager
def connect(path):
    db = sqlite3.connect(path, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    try:
        with db:
            yield db
    finally:
        db.close()


def migrate(path, *, target_version: int | None = None):
    """Apply pending migrations in order. A cutoff version is honored for tests."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with connect(path) as db:
        db.execute('PRAGMA journal_mode=WAL')
        db.execute(
            'CREATE TABLE IF NOT EXISTS schema_migrations '
            '(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)'
        )
        current = db.execute('SELECT MAX(version) FROM schema_migrations').fetchone()[0] or 0
        if target_version is not None and current > target_version:
            raise RuntimeError('Migration cutoff cannot downgrade an existing database')
        for migration in sorted(MIGRATIONS_DIR.glob('[0-9][0-9][0-9]_*.sql')):
            version = int(migration.name.split('_', 1)[0])
            if target_version is not None and version > target_version:
                break
            if db.execute('SELECT 1 FROM schema_migrations WHERE version=?', (version,)).fetchone() is None:
                db.executescript(migration.read_text(encoding='utf-8'))
                db.execute(
                    "INSERT INTO schema_migrations (version, applied_at) "
                    "VALUES (?, strftime('%Y-%m-%dT%H:%M:%fZ','now'))",
                    (version,),
                )
        errors = db.execute('PRAGMA foreign_key_check').fetchall()
        if errors:
            raise RuntimeError(f'Foreign key integrity check failed: {errors}')
