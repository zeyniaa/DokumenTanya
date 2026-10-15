import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from uuid import uuid4

from .config import settings


def uid():
    return str(uuid4())


def now():
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def connection():
    db = sqlite3.connect(settings().data_dir / "app.sqlite", timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def initialize():
    with connection() as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.executescript("""
        CREATE TABLE IF NOT EXISTS documents(
          id TEXT PRIMARY KEY, owner TEXT NOT NULL, name TEXT NOT NULL, hash TEXT NOT NULL,
          status TEXT NOT NULL, active_version TEXT, pages INTEGER DEFAULT 0,
          created TEXT NOT NULL, UNIQUE(owner,hash));
        CREATE TABLE IF NOT EXISTS versions(
          id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
          number INTEGER NOT NULL, content TEXT NOT NULL, created TEXT NOT NULL,
          UNIQUE(document_id,number));
        CREATE TABLE IF NOT EXISTS jobs(
          id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
          owner TEXT NOT NULL, status TEXT NOT NULL, stage TEXT NOT NULL,
          error TEXT, created TEXT NOT NULL, finished TEXT, payload TEXT);
        CREATE TABLE IF NOT EXISTS conversations(
          id TEXT PRIMARY KEY, owner TEXT NOT NULL, document_ids TEXT NOT NULL, created TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS messages(
          id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
          request_id TEXT NOT NULL, question TEXT NOT NULL, status TEXT NOT NULL,
          response TEXT, created TEXT NOT NULL, UNIQUE(conversation_id,request_id));
        CREATE INDEX IF NOT EXISTS owner_docs ON documents(owner);
        CREATE INDEX IF NOT EXISTS owner_convs ON conversations(owner);
        """)
        # Additive migration keeps existing documents and conversations intact.
        columns = {row[1] for row in db.execute("PRAGMA table_info(jobs)")}
        for name, declaration in {
            "progress_percent": "INTEGER NOT NULL DEFAULT 0",
            "pages_done": "INTEGER NOT NULL DEFAULT 0",
            "pages_total": "INTEGER NOT NULL DEFAULT 0",
            "phase": "TEXT NOT NULL DEFAULT 'queued'",
        }.items():
            if name not in columns:
                db.execute(f"ALTER TABLE jobs ADD COLUMN {name} {declaration}")


def one(sql, parameters=()):
    with connection() as db:
        row = db.execute(sql, parameters).fetchone()
        return dict(row) if row else None


def many(sql, parameters=()):
    with connection() as db:
        return [dict(row) for row in db.execute(sql, parameters)]


def execute(sql, parameters=()):
    with connection() as db:
        db.execute(sql, parameters)


def version_content(version_id):
    row = one("SELECT content FROM versions WHERE id=?", (version_id,))
    return json.loads(row["content"]) if row else None
