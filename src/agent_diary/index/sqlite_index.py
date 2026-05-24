from __future__ import annotations

from contextlib import closing
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS entries (
  entry_id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  title TEXT,
  source TEXT NOT NULL,
  author_role TEXT NOT NULL,
  raw_file_path TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS artifacts (
  artifact_id TEXT PRIMARY KEY,
  entry_id TEXT NOT NULL,
  created_at TEXT NOT NULL,
  artifact_type TEXT NOT NULL,
  producer TEXT NOT NULL,
  content TEXT NOT NULL,
  FOREIGN KEY (entry_id) REFERENCES entries(entry_id)
);

CREATE TABLE IF NOT EXISTS memory_index (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  entry_id TEXT NOT NULL,
  artifact_id TEXT,
  created_at TEXT NOT NULL,
  memory_text TEXT NOT NULL,
  tags TEXT,
  FOREIGN KEY (entry_id) REFERENCES entries(entry_id),
  FOREIGN KEY (artifact_id) REFERENCES artifacts(artifact_id)
);
"""


def bootstrap_sqlite(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(db_path)) as conn:
        conn.executescript(SCHEMA)
        cols = {row[1] for row in conn.execute("PRAGMA table_info(memory_index)").fetchall()}
        if "created_at" not in cols:
            # Legacy scaffold compatibility: add with a safe constant default for existing rows.
            conn.execute("ALTER TABLE memory_index ADD COLUMN created_at TEXT NOT NULL DEFAULT ''")
        conn.execute("UPDATE memory_index SET created_at = '' WHERE created_at IS NULL")
        conn.commit()
