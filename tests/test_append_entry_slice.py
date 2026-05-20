from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from agent_diary.config import default_paths
from agent_diary.index.sqlite_index import bootstrap_sqlite
from agent_diary.service.handlers import (
    append_entry,
    attach_artifact,
    fetch_entry_detail,
    fetch_raw_entry,
    list_entries,
    produce_open_loops,
    search_memory,
    status,
)
from agent_diary.storage.files import ensure_data_dirs


class AppendEntrySliceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.paths = default_paths(self.root)
        ensure_data_dirs(self.paths)
        bootstrap_sqlite(self.paths.sqlite_path)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_append_entry_writes_raw_file_at_expected_path(self) -> None:
        created_at = "2026-05-20T10:00:00+00:00"
        result = append_entry(
            self.paths,
            {
                "entry_type": "manual_note",
                "source": "cli",
                "author_role": "human",
                "content": "hello diary",
                "created_at": created_at,
                "metadata": {"mood": "focused"},
            },
        )

        raw_file = Path(result["raw_file"])
        self.assertTrue(raw_file.exists())
        self.assertEqual(raw_file.parent, self.paths.entries_dir / "2026" / "05" / "20")

        body = json.loads(raw_file.read_text(encoding="utf-8"))
        self.assertEqual(body["entry_id"], result["entry_id"])
        self.assertEqual(body["content"], "hello diary")

    def test_append_entry_registers_index_row(self) -> None:
        created_at = "2026-05-20T11:00:00+00:00"
        result = append_entry(
            self.paths,
            {
                "entry_type": "chat_log",
                "source": "openclaw",
                "author_role": "agent",
                "content": "indexed text",
                "created_at": created_at,
            },
        )

        with sqlite3.connect(self.paths.sqlite_path) as conn:
            row = conn.execute(
                "SELECT entry_id, created_at, source, author_role, raw_file_path FROM entries WHERE entry_id = ?",
                (result["entry_id"],),
            ).fetchone()

        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(row[0], result["entry_id"])
        self.assertEqual(row[1], created_at)
        self.assertEqual(row[2], "openclaw")
        self.assertEqual(row[3], "agent")
        self.assertEqual(row[4], result["raw_file"])

    def test_fetch_raw_entry_returns_authoritative_record(self) -> None:
        result = append_entry(
            self.paths,
            {
                "entry_type": "manual_note",
                "source": "cli",
                "author_role": "human",
                "content": "authoritative content",
                "created_at": "2026-05-20T12:00:00+00:00",
                "metadata": {"tag": "important"},
            },
        )

        fetched = fetch_raw_entry(self.paths, {"entry_id": result["entry_id"]})
        self.assertEqual(fetched["entry"]["entry_id"], result["entry_id"])
        self.assertEqual(fetched["entry"]["content"], "authoritative content")
        self.assertEqual(fetched["entry"]["metadata"], {"tag": "important"})

    def test_cli_append_entry_command_works(self) -> None:
        cmd = [
            sys.executable,
            "-m",
            "agent_diary.cli.main",
            "--json",
            "append-entry",
            "--entry-type",
            "manual_note",
            "--source",
            "cli",
            "--author-role",
            "human",
            "--content",
            "cli flow",
            "--created-at",
            "2026-05-20T13:00:00+00:00",
        ]

        env = os.environ.copy()
        env["PYTHONPATH"] = str(Path.cwd() / "src")
        completed = subprocess.run(
            cmd,
            cwd=self.root,
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )

        out = json.loads(completed.stdout)
        self.assertIn("entry_id", out)
        self.assertIn("raw_file", out)
        self.assertTrue(Path(out["raw_file"]).exists())

    def test_status_handler_contract(self) -> None:
        body = status(self.paths)
        self.assertTrue(body["ok"])
        self.assertEqual(body["sqlite_path"], str(self.paths.sqlite_path))

    def test_attach_compressed_memory_artifact_creates_memory_index_row(self) -> None:
        entry = append_entry(
            self.paths,
            {
                "entry_type": "chat_log",
                "source": "openclaw",
                "author_role": "agent",
                "content": "raw truth entry",
                "created_at": "2026-05-21T09:00:00+00:00",
            },
        )

        attached = attach_artifact(
            self.paths,
            {
                "entry_id": entry["entry_id"],
                "artifact_type": "compressed-memory",
                "producer": "agent-v1",
                "content": "user prefers concise status updates",
                "created_at": "2026-05-21T09:01:00+00:00",
            },
        )

        self.assertTrue(Path(attached["artifact_file"]).exists())
        self.assertTrue(attached["indexed_in_memory"])

        with sqlite3.connect(self.paths.sqlite_path) as conn:
            row = conn.execute(
                """
                SELECT entry_id, artifact_id, created_at, memory_text
                FROM memory_index
                WHERE artifact_id = ?
                """,
                (attached["artifact_id"],),
            ).fetchone()

        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(row[0], entry["entry_id"])
        self.assertEqual(row[1], attached["artifact_id"])
        self.assertEqual(row[2], "2026-05-21T09:01:00+00:00")
        self.assertEqual(row[3], "user prefers concise status updates")

    def test_search_memory_returns_match_linked_to_entry_id(self) -> None:
        entry = append_entry(
            self.paths,
            {
                "entry_type": "chat_log",
                "source": "openclaw",
                "author_role": "agent",
                "content": "raw discussion",
                "created_at": "2026-05-21T10:00:00+00:00",
            },
        )
        attach_artifact(
            self.paths,
            {
                "entry_id": entry["entry_id"],
                "artifact_type": "memory",
                "producer": "agent-v1",
                "content": "customer project deadline is friday",
                "created_at": "2026-05-21T10:01:00+00:00",
            },
        )

        results = search_memory(self.paths, {"query": "deadline", "limit": 10})
        self.assertEqual(results["query"], "deadline")
        self.assertEqual(len(results["matches"]), 1)
        hit = results["matches"][0]
        self.assertEqual(hit["entry_id"], entry["entry_id"])
        self.assertEqual(hit["fetch_raw_entry"]["entry_id"], entry["entry_id"])
        self.assertIn("deadline", hit["match_text"])
        self.assertNotIn("raw_file_path", hit)
        self.assertLessEqual(len(hit["match_text"]), 130)

    def test_fetch_raw_entry_after_search_hit_remains_truth_path(self) -> None:
        entry = append_entry(
            self.paths,
            {
                "entry_type": "manual_note",
                "source": "cli",
                "author_role": "human",
                "content": "raw truth should remain authoritative",
                "created_at": "2026-05-21T11:00:00+00:00",
            },
        )
        attach_artifact(
            self.paths,
            {
                "entry_id": entry["entry_id"],
                "artifact_type": "compressed-memory",
                "producer": "agent-v1",
                "content": "summary: raw truth is authoritative",
                "created_at": "2026-05-21T11:01:00+00:00",
            },
        )

        search = search_memory(self.paths, {"query": "authoritative", "limit": 5})
        hit_entry_id = search["matches"][0]["entry_id"]

        fetched = fetch_raw_entry(self.paths, {"entry_id": hit_entry_id})
        self.assertEqual(fetched["entry"]["entry_id"], entry["entry_id"])
        self.assertEqual(fetched["entry"]["content"], "raw truth should remain authoritative")

    def test_bootstrap_legacy_memory_index_adds_created_at_safely(self) -> None:
        legacy_db = self.root / "legacy.db"
        with sqlite3.connect(legacy_db) as conn:
            conn.executescript(
                """
                CREATE TABLE entries (
                  entry_id TEXT PRIMARY KEY,
                  created_at TEXT NOT NULL,
                  title TEXT,
                  source TEXT NOT NULL,
                  author_role TEXT NOT NULL,
                  raw_file_path TEXT NOT NULL
                );
                CREATE TABLE artifacts (
                  artifact_id TEXT PRIMARY KEY,
                  entry_id TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  artifact_type TEXT NOT NULL,
                  producer TEXT NOT NULL,
                  content TEXT NOT NULL
                );
                CREATE TABLE memory_index (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  entry_id TEXT NOT NULL,
                  artifact_id TEXT,
                  memory_text TEXT NOT NULL,
                  tags TEXT
                );
                """
            )
            conn.execute(
                "INSERT INTO memory_index(entry_id, artifact_id, memory_text, tags) VALUES (?, ?, ?, ?)",
                ("entry_legacy", "artifact_legacy", "legacy memory text", None),
            )
            conn.commit()

        bootstrap_sqlite(legacy_db)

        with sqlite3.connect(legacy_db) as conn:
            cols = {row[1] for row in conn.execute("PRAGMA table_info(memory_index)").fetchall()}
            created_at = conn.execute(
                "SELECT created_at FROM memory_index WHERE artifact_id = ?",
                ("artifact_legacy",),
            ).fetchone()

        self.assertIn("created_at", cols)
        self.assertIsNotNone(created_at)
        assert created_at is not None
        self.assertEqual(created_at[0], "")

    def test_search_memory_ranks_stronger_matches_first(self) -> None:
        strong_entry = append_entry(
            self.paths,
            {
                "entry_type": "chat_log",
                "source": "openclaw",
                "author_role": "agent",
                "content": "raw strong",
                "created_at": "2026-05-22T09:00:00+00:00",
            },
        )
        weak_entry = append_entry(
            self.paths,
            {
                "entry_type": "chat_log",
                "source": "openclaw",
                "author_role": "agent",
                "content": "raw weak",
                "created_at": "2026-05-22T09:00:01+00:00",
            },
        )

        attach_artifact(
            self.paths,
            {
                "entry_id": weak_entry["entry_id"],
                "artifact_type": "memory",
                "producer": "agent-v1",
                "content": "deadline mentioned once",
                "created_at": "2026-05-22T09:01:00+00:00",
            },
        )
        attach_artifact(
            self.paths,
            {
                "entry_id": strong_entry["entry_id"],
                "artifact_type": "memory",
                "producer": "agent-v1",
                "content": "project deadline friday and deadline planning details",
                "created_at": "2026-05-22T09:01:01+00:00",
            },
        )

        results = search_memory(self.paths, {"query": "deadline friday", "limit": 10})
        self.assertEqual(results["matches"][0]["entry_id"], strong_entry["entry_id"])
        self.assertIn("deadline", results["matches"][0]["match_text"])

    def test_search_memory_returns_compact_snippet_instead_of_full_text(self) -> None:
        entry = append_entry(
            self.paths,
            {
                "entry_type": "chat_log",
                "source": "openclaw",
                "author_role": "agent",
                "content": "raw content",
                "created_at": "2026-05-22T10:00:00+00:00",
            },
        )
        long_text = (
            "This is a long compressed memory entry that includes setup context, "
            "follow-up notes, and the target phrase deadline near the middle of the text "
            "with additional trailing details that should be truncated for compact recall output."
        )
        attach_artifact(
            self.paths,
            {
                "entry_id": entry["entry_id"],
                "artifact_type": "compressed-memory",
                "producer": "agent-v1",
                "content": long_text,
                "created_at": "2026-05-22T10:01:00+00:00",
            },
        )

        results = search_memory(self.paths, {"query": "deadline", "limit": 5})
        snippet = results["matches"][0]["match_text"]
        self.assertIn("deadline", snippet.lower())
        self.assertLess(len(snippet), len(long_text))

    def test_list_entries_returns_human_browse_fields(self) -> None:
        append_entry(
            self.paths,
            {
                "entry_type": "manual_note",
                "source": "cli",
                "author_role": "human",
                "content": "This is a human-readable diary entry body for preview testing.",
                "created_at": "2026-05-23T09:00:00+00:00",
            },
        )

        out = list_entries(self.paths, {"limit": 10, "offset": 0})
        self.assertEqual(out["limit"], 10)
        self.assertEqual(out["offset"], 0)
        self.assertGreaterEqual(len(out["items"]), 1)
        item = out["items"][0]
        self.assertIn("entry_id", item)
        self.assertIn("created_at", item)
        self.assertIn("entry_type", item)
        self.assertIn("source", item)
        self.assertIn("author_role", item)
        self.assertIn("preview", item)
        self.assertEqual(item["entry_type"], "manual_note")
        self.assertEqual(item["source"], "cli")
        self.assertEqual(item["author_role"], "human")

    def test_fetch_entry_detail_returns_raw_primary_body(self) -> None:
        entry = append_entry(
            self.paths,
            {
                "entry_type": "chat_log",
                "source": "openclaw",
                "author_role": "agent",
                "content": "verbatim primary body",
                "created_at": "2026-05-23T10:00:00+00:00",
            },
        )
        attach_artifact(
            self.paths,
            {
                "entry_id": entry["entry_id"],
                "artifact_type": "compressed-memory",
                "producer": "agent-v1",
                "content": "secondary memory summary",
                "created_at": "2026-05-23T10:01:00+00:00",
            },
        )

        detail = fetch_entry_detail(self.paths, {"entry_id": entry["entry_id"]})
        self.assertEqual(detail["entry_id"], entry["entry_id"])
        self.assertEqual(detail["raw_entry"]["content"], "verbatim primary body")
        self.assertEqual(detail["truth_model"]["primary"], "raw_entry")
        self.assertEqual(detail["truth_model"]["secondary"], "artifacts")

    def test_fetch_entry_detail_includes_artifact_linkage_metadata(self) -> None:
        entry = append_entry(
            self.paths,
            {
                "entry_type": "manual_note",
                "source": "cli",
                "author_role": "human",
                "content": "truth record",
                "created_at": "2026-05-23T11:00:00+00:00",
            },
        )
        attached = attach_artifact(
            self.paths,
            {
                "entry_id": entry["entry_id"],
                "artifact_type": "memory",
                "producer": "agent-v1",
                "content": "memory helper",
                "created_at": "2026-05-23T11:01:00+00:00",
            },
        )

        detail = fetch_entry_detail(self.paths, {"entry_id": entry["entry_id"]})
        self.assertEqual(len(detail["artifacts"]), 1)
        artifact = detail["artifacts"][0]
        self.assertEqual(artifact["artifact_id"], attached["artifact_id"])
        self.assertEqual(artifact["artifact_type"], "memory")
        self.assertEqual(artifact["producer"], "agent-v1")

    def test_fetch_entry_detail_includes_open_loop_payload_for_analysis_artifact(self) -> None:
        e1 = append_entry(
            self.paths,
            {
                "entry_type": "chat_log",
                "source": "openclaw",
                "author_role": "agent",
                "content": "TODO: follow up on budget question.",
                "created_at": "2026-05-25T09:00:00+00:00",
            },
        )
        append_entry(
            self.paths,
            {
                "entry_type": "manual_note",
                "source": "cli",
                "author_role": "human",
                "content": "Pending decision on budget timeline.",
                "created_at": "2026-05-25T10:00:00+00:00",
            },
        )
        produced = produce_open_loops(self.paths, {"limit": 5})
        anchor_entry_id = produced["source_entry_ids"][0]
        detail = fetch_entry_detail(self.paths, {"entry_id": anchor_entry_id})
        open_loop_artifacts = [a for a in detail["artifacts"] if a["artifact_type"] == "analysis:open-loop"]
        self.assertGreaterEqual(len(open_loop_artifacts), 1)
        self.assertIn("open_loops", open_loop_artifacts[0])
        self.assertIsInstance(open_loop_artifacts[0]["open_loops"], list)

    def test_produce_open_loops_emits_analysis_artifact(self) -> None:
        append_entry(
            self.paths,
            {
                "entry_type": "chat_log",
                "source": "openclaw",
                "author_role": "agent",
                "content": "TODO: follow up with customer on quote timeline.",
                "created_at": "2026-05-24T09:00:00+00:00",
            },
        )
        append_entry(
            self.paths,
            {
                "entry_type": "manual_note",
                "source": "cli",
                "author_role": "human",
                "content": "Still pending: should send project update by Friday.",
                "created_at": "2026-05-24T10:00:00+00:00",
            },
        )

        produced = produce_open_loops(self.paths, {"limit": 10})
        self.assertGreaterEqual(produced["loop_count"], 1)
        artifact_file = Path(produced["artifact_file"])
        self.assertTrue(artifact_file.exists())

        artifact_body = json.loads(artifact_file.read_text(encoding="utf-8"))
        self.assertEqual(artifact_body["artifact_type"], "analysis:open-loop")
        content = json.loads(artifact_body["content"])
        self.assertIn("loops", content)
        self.assertGreaterEqual(len(content["loops"]), 1)

    def test_produce_open_loops_preserves_lineage_source_entry_ids(self) -> None:
        e1 = append_entry(
            self.paths,
            {
                "entry_type": "chat_log",
                "source": "openclaw",
                "author_role": "agent",
                "content": "Pending question: do we have final budget?",
                "created_at": "2026-05-24T11:00:00+00:00",
            },
        )
        e2 = append_entry(
            self.paths,
            {
                "entry_type": "chat_log",
                "source": "openclaw",
                "author_role": "agent",
                "content": "TODO follow-up tomorrow about budget approval.",
                "created_at": "2026-05-24T12:00:00+00:00",
            },
        )

        produced = produce_open_loops(self.paths, {"entry_ids": [e1["entry_id"], e2["entry_id"]], "limit": 10})
        artifact_file = Path(produced["artifact_file"])
        artifact_body = json.loads(artifact_file.read_text(encoding="utf-8"))
        metadata = artifact_body["metadata"]
        self.assertEqual(sorted(metadata["source_entry_ids"]), sorted([e1["entry_id"], e2["entry_id"]]))
        loops = json.loads(artifact_body["content"])["loops"]
        self.assertTrue(any(e1["entry_id"] in loop["supporting_entry_ids"] or e2["entry_id"] in loop["supporting_entry_ids"] for loop in loops))

    def test_produce_open_loops_does_not_mutate_raw_entries(self) -> None:
        entry = append_entry(
            self.paths,
            {
                "entry_type": "manual_note",
                "source": "cli",
                "author_role": "human",
                "content": "TODO: unresolved billing question.",
                "created_at": "2026-05-24T13:00:00+00:00",
            },
        )
        before = fetch_raw_entry(self.paths, {"entry_id": entry["entry_id"]})["entry"]
        produce_open_loops(self.paths, {"entry_ids": [entry["entry_id"]], "limit": 5})
        after = fetch_raw_entry(self.paths, {"entry_id": entry["entry_id"]})["entry"]
        self.assertEqual(before, after)

    def test_produce_open_loops_suppresses_stray_question_false_positive(self) -> None:
        entry = append_entry(
            self.paths,
            {
                "entry_type": "manual_note",
                "source": "cli",
                "author_role": "human",
                "content": "What a day? Great weather and coffee.",
                "created_at": "2026-05-24T14:00:00+00:00",
            },
        )
        produced = produce_open_loops(self.paths, {"entry_ids": [entry["entry_id"]], "limit": 5})
        artifact_file = Path(produced["artifact_file"])
        loops = json.loads(json.loads(artifact_file.read_text(encoding="utf-8"))["content"])["loops"]
        self.assertEqual(len(loops), 0)

    def test_produce_open_loops_does_not_emit_clearly_closed_language(self) -> None:
        entry = append_entry(
            self.paths,
            {
                "entry_type": "chat_log",
                "source": "openclaw",
                "author_role": "agent",
                "content": "TODO: finalize deployment checklist. This is done and resolved.",
                "created_at": "2026-05-24T15:00:00+00:00",
            },
        )
        produced = produce_open_loops(self.paths, {"entry_ids": [entry["entry_id"]], "limit": 5})
        artifact_file = Path(produced["artifact_file"])
        loops = json.loads(json.loads(artifact_file.read_text(encoding="utf-8"))["content"])["loops"]
        self.assertEqual(len(loops), 0)


if __name__ == "__main__":
    unittest.main()
