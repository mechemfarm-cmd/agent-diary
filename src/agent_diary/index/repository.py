from __future__ import annotations

import sqlite3
import re
from pathlib import Path
from typing import Any

from agent_diary.models.types import Artifact, RawEntry


def insert_entry(db_path: Path, entry: RawEntry, raw_file_path: str) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO entries(entry_id, created_at, title, source, author_role, raw_file_path)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (entry.entry_id, entry.created_at, entry.title, entry.source, entry.author_role, raw_file_path),
        )
        conn.commit()


def insert_artifact(db_path: Path, artifact: Artifact) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO artifacts(artifact_id, entry_id, created_at, artifact_type, producer, content)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                artifact.artifact_id,
                artifact.entry_id,
                artifact.created_at,
                artifact.artifact_type,
                artifact.producer,
                artifact.content,
            ),
        )
        conn.commit()


def search_memory(db_path: Path, query: str, limit: int = 20) -> list[dict[str, Any]]:
    # Search only the compressed memory index and return lightweight links.
    terms = [t for t in re.findall(r"\w+", query.lower()) if t]
    if not terms:
        return []

    like_params = [f"%{t}%" for t in terms]
    where_clause = " OR ".join(["LOWER(mi.memory_text) LIKE ?"] * len(like_params))

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            f"""
            SELECT
              mi.entry_id,
              mi.artifact_id,
              mi.created_at AS indexed_at,
              mi.memory_text AS match_text
            FROM memory_index mi
            WHERE {where_clause}
              AND NOT EXISTS (
                SELECT 1
                FROM memory_index newer
                WHERE newer.entry_id = mi.entry_id
                  AND (
                    newer.created_at > mi.created_at
                    OR (
                      newer.created_at = mi.created_at
                      AND COALESCE(newer.artifact_id, '') > COALESCE(mi.artifact_id, '')
                    )
                  )
              )
            ORDER BY mi.created_at DESC
            LIMIT ?
            """,
            (*like_params, max(limit * 5, limit)),
        ).fetchall()

    scored: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        text = str(item["match_text"]).lower()
        # Deterministic ranking: exact phrase > term coverage > frequency.
        phrase_bonus = 100 if query.lower() in text else 0
        coverage = sum(1 for term in terms if term in text)
        frequency = sum(text.count(term) for term in terms)
        item["_score"] = phrase_bonus + (coverage * 10) + frequency
        scored.append(item)

    scored.sort(key=lambda r: (r["_score"], r["indexed_at"]), reverse=True)
    return [{k: v for k, v in row.items() if k != "_score"} for row in scored[:limit]]


def get_entry_row(db_path: Path, entry_id: str) -> dict[str, Any] | None:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT entry_id, created_at, title, source, author_role, raw_file_path
            FROM entries
            WHERE entry_id = ?
            """,
            (entry_id,),
        ).fetchone()
    return dict(row) if row else None


def list_entry_rows(db_path: Path, *, limit: int = 20, offset: int = 0) -> list[dict[str, Any]]:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT entry_id, created_at, source, author_role, raw_file_path
            FROM entries
            ORDER BY created_at DESC, entry_id DESC
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        ).fetchall()
    return [dict(r) for r in rows]


def insert_memory_index_row(
    db_path: Path,
    *,
    entry_id: str,
    artifact_id: str,
    created_at: str,
    memory_text: str,
) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO memory_index(entry_id, artifact_id, created_at, memory_text, tags)
            VALUES (?, ?, ?, ?, ?)
            """,
            (entry_id, artifact_id, created_at, memory_text, None),
        )
        conn.commit()
