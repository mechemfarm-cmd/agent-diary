from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from agent_diary.cli.session_builder import TranscriptMessage, build_session_entries, build_session_jsonl
from agent_diary.cli.transcript_adapter import adapt_session_export
from agent_diary.config import default_paths
from agent_diary.index.sqlite_index import bootstrap_sqlite
from agent_diary.service.handlers import (
    append_entry,
    attach_artifact,
    fetch_entry_detail,
    fetch_raw_entry,
    import_session_jsonl,
    list_entries,
    list_imports,
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

    def test_import_session_jsonl_writes_manifest_and_truthful_ingestion_metadata(self) -> None:
        source_file = self.root / "session.jsonl"
        source_file.write_text(
            "\n".join(
                [
                    json.dumps(
                        {
                            "entry_type": "chat_log",
                            "source": "telegram-direct-import",
                            "author_role": "human",
                            "created_at": "2026-05-25T12:00:00+00:00",
                            "content": "We should preserve the raw record.",
                            "metadata": {"source_message_id": "m1"},
                        }
                    ),
                    json.dumps(
                        {
                            "entry_type": "chat_log",
                            "source": "telegram-direct-import",
                            "author_role": "agent",
                            "created_at": "2026-05-25T12:01:00+00:00",
                            "content": "Agreed. Let's make imports idempotent.",
                            "metadata": {"source_message_id": "m2"},
                        }
                    ),
                ]
            ),
            encoding="utf-8",
        )

        result = import_session_jsonl(
            self.paths,
            {
                "path": str(source_file),
                "import_id": "import_test_truthful",
                "source_session_id": "session-123",
                "source_conversation_id": "telegram:713733361",
            },
        )

        self.assertEqual(result["imported_count"], 2)
        self.assertEqual(result["skipped_count"], 0)
        manifest_path = Path(result["manifest_path"])
        self.assertTrue(manifest_path.exists())
        ledger_path = Path(result["ledger_path"])
        self.assertTrue(ledger_path.exists())

        entry_id = result["imported"][0]["entry_id"]
        fetched = fetch_raw_entry(self.paths, {"entry_id": entry_id})
        ingestion = fetched["entry"]["metadata"]["ingestion"]
        self.assertTrue(ingestion["truthful_source"])
        self.assertEqual(ingestion["import_mode"], "session_jsonl")
        self.assertEqual(ingestion["import_id"], "import_test_truthful")
        self.assertEqual(ingestion["source_session_id"], "session-123")
        self.assertEqual(ingestion["source_conversation_id"], "telegram:713733361")

    def test_import_session_jsonl_skips_duplicate_source_items_on_repeat_run(self) -> None:
        source_file = self.root / "repeat.jsonl"
        source_file.write_text(
            json.dumps(
                {
                    "entry_type": "chat_log",
                    "source": "telegram-direct-import",
                    "author_role": "human",
                    "created_at": "2026-05-25T13:00:00+00:00",
                    "content": "Same message should not import twice.",
                    "metadata": {"source_message_id": "dup-1"},
                }
            )
            + "\n",
            encoding="utf-8",
        )

        first = import_session_jsonl(self.paths, {"path": str(source_file), "import_id": "import_dup_first"})
        second = import_session_jsonl(self.paths, {"path": str(source_file), "import_id": "import_dup_second"})

        self.assertEqual(first["imported_count"], 1)
        self.assertEqual(second["imported_count"], 0)
        self.assertEqual(second["skipped_count"], 1)
        self.assertEqual(second["skipped"][0]["reason"], "duplicate_source_item")

    def test_import_session_jsonl_dry_run_reports_without_writing_entries(self) -> None:
        source_file = self.root / "dry-run.jsonl"
        source_file.write_text(
            json.dumps(
                {
                    "entry_type": "chat_log",
                    "source": "telegram-direct-import",
                    "author_role": "human",
                    "created_at": "2026-05-25T14:00:00+00:00",
                    "content": "Preview this import only.",
                    "metadata": {"source_message_id": "dry-1"},
                }
            )
            + "\n",
            encoding="utf-8",
        )

        result = import_session_jsonl(self.paths, {"path": str(source_file), "dry_run": True, "import_id": "import_dry"})

        self.assertEqual(result["imported_count"], 1)
        self.assertEqual(result["skipped_count"], 0)
        self.assertNotIn("ledger_path", result)
        self.assertTrue(Path(result["manifest_path"]).exists())
        self.assertEqual(list(self.paths.entries_dir.glob("**/*.json")), [])

    def test_build_session_entries_groups_messages_and_preserves_ids(self) -> None:
        transcript = self.root / "transcript.jsonl"
        transcript.write_text(
            "\n".join(
                [
                    json.dumps({"message_id": "1", "created_at": "2026-05-25T10:00:00+00:00", "author_role": "human", "speaker": "Bill", "content": "First"}),
                    json.dumps({"message_id": "2", "created_at": "2026-05-25T10:05:00+00:00", "author_role": "agent", "speaker": "Tom", "content": "Second"}),
                    json.dumps({"message_id": "3", "created_at": "2026-05-25T11:10:00+00:00", "author_role": "human", "speaker": "Bill", "content": "Third"}),
                ]
            ),
            encoding="utf-8",
        )
        out_path = self.root / "built.jsonl"
        result = build_session_jsonl(
            input_path=transcript,
            output_path=out_path,
            source="telegram-direct-import",
            gap_minutes=30,
            max_chars=4000,
            min_messages_before_gap_split=1,
            min_chars_before_gap_split=1,
        )

        self.assertEqual(result["message_count"], 3)
        self.assertEqual(result["entry_count"], 2)
        built_lines = [json.loads(line) for line in out_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        self.assertEqual(built_lines[0]["author_role"], "mixed")
        self.assertEqual(built_lines[0]["metadata"]["source_message_ids"], ["1", "2"])
        self.assertIn("Bill: First", built_lines[0]["content"])
        self.assertIn("Tom: Second", built_lines[0]["content"])
        self.assertEqual(built_lines[1]["metadata"]["source_message_ids"], ["3"])

    def test_build_session_entries_splits_on_max_chars(self) -> None:
        messages = [
            TranscriptMessage(
                message_id="1",
                created_at="2026-05-25T10:00:00+00:00",
                author_role="human",
                speaker="Bill",
                content="A" * 160,
                metadata={},
            ),
            TranscriptMessage(
                message_id="2",
                created_at="2026-05-25T10:01:00+00:00",
                author_role="agent",
                speaker="Tom",
                content="B" * 160,
                metadata={},
            ),
        ]
        built = build_session_entries(
            messages,
            source="telegram-direct-import",
            gap_minutes=30,
            max_chars=200,
        )
        self.assertEqual(len(built), 2)

    def test_build_session_entries_short_contiguous_exchange_stays_one_chunk(self) -> None:
        messages = [
            TranscriptMessage("1", "2026-05-25T10:00:00+00:00", "human", "Bill", "Hi", {}),
            TranscriptMessage("2", "2026-05-25T10:01:00+00:00", "agent", "Tom", "Hello", {}),
            TranscriptMessage("3", "2026-05-25T10:02:00+00:00", "human", "Bill", "Need quick help", {}),
        ]
        built = build_session_entries(messages, source="telegram-direct-import", gap_minutes=30, max_chars=4000, max_messages=40)
        self.assertEqual(len(built), 1)
        self.assertEqual(built[0]["metadata"]["source_message_ids"], ["1", "2", "3"])

    def test_build_session_entries_long_gap_unrelated_restart_splits(self) -> None:
        messages = [
            TranscriptMessage("1", "2026-05-25T10:00:00+00:00", "human", "Bill", "Can you send the deployment notes?", {}),
            TranscriptMessage("2", "2026-05-25T12:00:00+00:00", "human", "Bill", "Different topic: lunch tomorrow?", {}),
        ]
        built = build_session_entries(messages, source="telegram-direct-import", gap_minutes=30, max_chars=4000, max_messages=40)
        self.assertEqual(len(built), 2)

    def test_build_session_entries_long_gap_obvious_continuation_stays_together(self) -> None:
        messages = [
            TranscriptMessage("1", "2026-05-25T10:00:00+00:00", "human", "Bill", "Can you send the deployment notes?", {}),
            TranscriptMessage("2", "2026-05-25T12:00:00+00:00", "agent", "Tom", "Done, sent now.", {}),
        ]
        built = build_session_entries(messages, source="telegram-direct-import", gap_minutes=30, max_chars=4000, max_messages=40)
        self.assertEqual(len(built), 1)
        self.assertEqual(built[0]["metadata"]["source_message_ids"], ["1", "2"])

    def test_build_session_entries_long_gap_same_task_groups_more_aggressively(self) -> None:
        messages = [
            TranscriptMessage("1", "2026-05-25T10:00:00+00:00", "human", "Bill", "Need a codex build fix for android release pipeline.", {}),
            TranscriptMessage("2", "2026-05-25T10:05:00+00:00", "agent", "Tom", "I can work that build issue.", {}),
            TranscriptMessage("3", "2026-05-25T11:20:00+00:00", "human", "Bill", "The android build fix still matters; let's continue that pipeline task.", {}),
        ]
        built = build_session_entries(messages, source="telegram-direct-import", gap_minutes=30, max_chars=4000, max_messages=40)
        self.assertEqual(len(built), 1)
        self.assertEqual(built[0]["metadata"]["source_message_ids"], ["1", "2", "3"])

    def test_build_session_entries_splits_on_max_messages(self) -> None:
        messages = [
            TranscriptMessage("1", "2026-05-25T10:00:00+00:00", "human", "Bill", "one", {}),
            TranscriptMessage("2", "2026-05-25T10:01:00+00:00", "agent", "Tom", "two", {}),
            TranscriptMessage("3", "2026-05-25T10:02:00+00:00", "human", "Bill", "three", {}),
        ]
        built = build_session_entries(messages, source="telegram-direct-import", gap_minutes=30, max_chars=4000, max_messages=2)
        self.assertEqual(len(built), 2)
        self.assertEqual(built[0]["metadata"]["source_message_ids"], ["1", "2"])
        self.assertEqual(built[1]["metadata"]["source_message_ids"], ["3"])

    def test_build_session_entries_session_or_conversation_change_forces_split(self) -> None:
        messages = [
            TranscriptMessage(
                "1",
                "2026-05-25T10:00:00+00:00",
                "human",
                "Bill",
                "first",
                {"source_session_id": "s1", "source_conversation_id": "c1"},
            ),
            TranscriptMessage(
                "2",
                "2026-05-25T10:01:00+00:00",
                "agent",
                "Tom",
                "second",
                {"source_session_id": "s1", "source_conversation_id": "c2"},
            ),
        ]
        built = build_session_entries(messages, source="telegram-direct-import", gap_minutes=30, max_chars=4000, max_messages=40)
        self.assertEqual(len(built), 2)
        self.assertEqual(built[0]["metadata"]["source_conversation_id"], "c1")
        self.assertEqual(built[1]["metadata"]["source_conversation_id"], "c2")

    def test_build_transcript_jsonl_generic_message_jsonl_outputs_canonical_shape(self) -> None:
        source_file = self.root / "raw-generic.jsonl"
        source_file.write_text(
            "\n".join(
                [
                    json.dumps(
                        {
                            "id": "g1",
                            "timestamp": "2026-05-27T09:00:00+00:00",
                            "role": "user",
                            "speaker": "Bill",
                            "text": "Hello there",
                            "metadata": {"channel": "telegram"},
                        }
                    ),
                    json.dumps(
                        {
                            "message_id": "g2",
                            "created_at": "2026-05-27T09:01:00+00:00",
                            "author_role": "assistant",
                            "content": "Hi Bill",
                        }
                    ),
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        out_path = self.root / "transcript.jsonl"

        result = adapt_session_export(
            input_path=source_file,
            output_path=out_path,
            format_name="generic-message-jsonl",
            source_session_id="session-abc",
            source_conversation_id="conv-xyz",
        )

        self.assertEqual(result["message_count"], 2)
        lines = [json.loads(line) for line in out_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        self.assertEqual(lines[0]["message_id"], "g1")
        self.assertEqual(lines[0]["created_at"], "2026-05-27T09:00:00+00:00")
        self.assertEqual(lines[0]["author_role"], "human")
        self.assertEqual(lines[0]["speaker"], "Bill")
        self.assertEqual(lines[0]["content"], "Hello there")
        self.assertIn("metadata", lines[0])
        self.assertEqual(lines[0]["metadata"]["source_message_id"], "g1")
        self.assertEqual(lines[1]["author_role"], "agent")

    def test_build_transcript_jsonl_rejects_malformed_input(self) -> None:
        source_file = self.root / "bad-generic.jsonl"
        source_file.write_text(
            json.dumps(
                {
                    "id": "bad-1",
                    "timestamp": "2026-05-27T09:00:00+00:00",
                    "role": "user",
                    # content/text/message intentionally missing
                }
            )
            + "\n",
            encoding="utf-8",
        )

        with self.assertRaises(ValueError):
            adapt_session_export(
                input_path=source_file,
                output_path=self.root / "unused.jsonl",
                format_name="generic-message-jsonl",
            )

    def test_build_transcript_jsonl_openclaw_session_json_preserves_source_ids(self) -> None:
        source_file = self.root / "openclaw-session.json"
        source_file.write_text(
            json.dumps(
                {
                    "session_id": "oc-session-1",
                    "conversation_id": "oc-conv-1",
                    "messages": [
                        {
                            "id": "m-001",
                            "created_at": "2026-05-27T10:00:00+00:00",
                            "role": "user",
                            "speaker": "Willard",
                            "content": "Need follow-up reminder",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        out_path = self.root / "openclaw-transcript.jsonl"

        result = adapt_session_export(
            input_path=source_file,
            output_path=out_path,
            format_name="openclaw-session-json",
        )

        self.assertEqual(result["source_session_id"], "oc-session-1")
        self.assertEqual(result["source_conversation_id"], "oc-conv-1")
        row = json.loads(out_path.read_text(encoding="utf-8").splitlines()[0])
        self.assertEqual(row["message_id"], "m-001")
        self.assertEqual(row["created_at"], "2026-05-27T10:00:00+00:00")
        self.assertEqual(row["metadata"]["source_message_id"], "m-001")
        self.assertEqual(row["metadata"]["source_session_id"], "oc-session-1")
        self.assertEqual(row["metadata"]["source_conversation_id"], "oc-conv-1")

    def test_build_transcript_jsonl_openclaw_telegram_jsonl_preserves_truth_fields(self) -> None:
        source_file = self.root / "telegram-source.json"
        source_file.write_text(
            "\n".join(
                [
                    json.dumps(
                        {
                            "key": "default:713733361:5316",
                            "node": {
                                "sourceMessage": {
                                    "message_id": 5316,
                                    "from": {"id": 713733361, "is_bot": False, "username": "Willardmechem"},
                                    "chat": {"id": 713733361, "type": "private"},
                                    "date": 1778932179,
                                    "text": "so looks like we're all good",
                                }
                            },
                        }
                    )
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        out_path = self.root / "telegram-transcript.jsonl"
        result = adapt_session_export(
            input_path=source_file,
            output_path=out_path,
            format_name="openclaw-telegram-jsonl",
        )

        self.assertEqual(result["message_count"], 1)
        self.assertEqual(result["source_conversation_id"], "telegram:713733361")
        row = json.loads(out_path.read_text(encoding="utf-8").splitlines()[0])
        self.assertEqual(row["message_id"], "5316")
        self.assertEqual(row["author_role"], "human")
        self.assertEqual(row["speaker"], "Willardmechem")
        self.assertEqual(row["content"], "so looks like we're all good")
        self.assertTrue(row["created_at"].startswith("2026-"))
        self.assertEqual(row["metadata"]["source_key"], "default:713733361:5316")
        self.assertEqual(row["metadata"]["source_message_id"], "5316")
        self.assertEqual(row["metadata"]["telegram_chat_id"], 713733361)

    def test_build_transcript_jsonl_openclaw_telegram_jsonl_rejects_missing_source_message(self) -> None:
        source_file = self.root / "telegram-bad.json"
        source_file.write_text(json.dumps({"key": "bad", "node": {}}) + "\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            adapt_session_export(
                input_path=source_file,
                output_path=self.root / "unused-telegram.jsonl",
                format_name="openclaw-telegram-jsonl",
            )

    def test_build_transcript_jsonl_openclaw_session_jsonl_maps_user_and_assistant_text(self) -> None:
        source_file = self.root / "session-log.jsonl"
        source_file.write_text(
            "\n".join(
                [
                    json.dumps(
                        {
                            "type": "session",
                            "version": 3,
                            "id": "session-123",
                            "timestamp": "2026-05-21T06:46:22.209Z",
                            "cwd": "/home/willard",
                        }
                    ),
                    json.dumps(
                        {
                            "type": "message",
                            "id": "msg-1",
                            "parentId": None,
                            "timestamp": "2026-05-21T06:46:22.208Z",
                            "message": {
                                "role": "user",
                                "content": "hello there",
                                "timestamp": 1779345982195,
                            },
                        }
                    ),
                    json.dumps(
                        {
                            "type": "message",
                            "id": "msg-2",
                            "parentId": "msg-1",
                            "timestamp": "2026-05-21T06:46:22.210Z",
                            "message": {
                                "role": "assistant",
                                "content": [
                                    {"type": "toolCall", "name": "memory_search"},
                                    {"type": "text", "text": "Here is the reply text."},
                                    {"type": "toolResult", "toolCallId": "x"},
                                ],
                                "timestamp": 1779345982210,
                            },
                        }
                    ),
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        out_path = self.root / "session-transcript.jsonl"

        result = adapt_session_export(
            input_path=source_file,
            output_path=out_path,
            format_name="openclaw-session-jsonl",
        )

        self.assertEqual(result["message_count"], 2)
        rows = [json.loads(line) for line in out_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        self.assertEqual(rows[0]["message_id"], "msg-1")
        self.assertEqual(rows[0]["author_role"], "human")
        self.assertEqual(rows[0]["speaker"], "User")
        self.assertEqual(rows[0]["content"], "hello there")
        self.assertEqual(rows[0]["metadata"]["source_session_id"], "session-123")
        self.assertNotIn("source_parent_id", rows[0]["metadata"])
        self.assertEqual(rows[1]["message_id"], "msg-2")
        self.assertEqual(rows[1]["author_role"], "agent")
        self.assertEqual(rows[1]["speaker"], "Assistant")
        self.assertEqual(rows[1]["content"], "Here is the reply text.")
        self.assertEqual(rows[1]["metadata"]["source_parent_id"], "msg-1")
        self.assertEqual(rows[1]["metadata"]["openclaw_message_role"], "assistant")
        self.assertEqual(rows[1]["metadata"]["source_session_cwd"], "/home/willard")

    def test_build_transcript_jsonl_openclaw_session_jsonl_skips_tool_only_assistant_messages(self) -> None:
        source_file = self.root / "session-tool-only.jsonl"
        source_file.write_text(
            "\n".join(
                [
                    json.dumps(
                        {
                            "type": "message",
                            "id": "msg-1",
                            "parentId": None,
                            "timestamp": "2026-05-21T06:46:22.210Z",
                            "message": {
                                "role": "assistant",
                                "content": [{"type": "toolCall", "name": "memory_search"}],
                                "timestamp": 1779345982210,
                            },
                        }
                    )
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        out_path = self.root / "session-tool-only-transcript.jsonl"

        result = adapt_session_export(
            input_path=source_file,
            output_path=out_path,
            format_name="openclaw-session-jsonl",
        )

        self.assertEqual(result["message_count"], 0)
        self.assertEqual(out_path.read_text(encoding="utf-8"), "")

    def test_build_transcript_jsonl_openclaw_session_jsonl_rejects_bad_message_record(self) -> None:
        source_file = self.root / "session-bad.jsonl"
        source_file.write_text(
            json.dumps(
                {
                    "type": "message",
                    "id": "msg-1",
                    "parentId": None,
                    "timestamp": "2026-05-21T06:46:22.210Z",
                    "message": "not an object",
                }
            )
            + "\n",
            encoding="utf-8",
        )
        with self.assertRaises(ValueError):
            adapt_session_export(
                input_path=source_file,
                output_path=self.root / "unused-session.jsonl",
                format_name="openclaw-session-jsonl",
            )

    def _write_openclaw_session_fixture(self, path: Path) -> None:
        path.write_text(
            "\n".join(
                [
                    json.dumps(
                        {
                            "type": "session",
                            "version": 3,
                            "id": "session-plain-1",
                            "timestamp": "2026-05-21T10:00:00.000Z",
                            "cwd": "/home/willard",
                        }
                    ),
                    json.dumps(
                        {
                            "type": "message",
                            "id": "m-1",
                            "parentId": None,
                            "timestamp": "2026-05-21T10:00:01.000Z",
                            "message": {
                                "role": "user",
                                "content": "hello there",
                                "timestamp": 1779360001000,
                            },
                        }
                    ),
                    json.dumps(
                        {
                            "type": "message",
                            "id": "m-2",
                            "parentId": "m-1",
                            "timestamp": "2026-05-21T10:00:02.000Z",
                            "message": {
                                "role": "assistant",
                                "content": [
                                    {"type": "toolCall", "name": "memory_search"},
                                    {"type": "text", "text": "hi there"},
                                    {"type": "toolResult", "toolCallId": "x"},
                                ],
                                "timestamp": 1779360002000,
                            },
                        }
                    ),
                    json.dumps(
                        {
                            "type": "message",
                            "id": "m-3",
                            "parentId": "m-2",
                            "timestamp": "2026-05-21T10:00:03.000Z",
                            "message": {
                                "role": "user",
                                "content": "what should we do next?",
                                "timestamp": 1779360003000,
                            },
                        }
                    ),
                    json.dumps(
                        {
                            "type": "message",
                            "id": "m-4",
                            "parentId": "m-3",
                            "timestamp": "2026-05-21T10:00:04.000Z",
                            "message": {
                                "role": "assistant",
                                "content": [
                                    {"type": "text", "text": "We should keep the scope narrow."}
                                ],
                                "timestamp": 1779360004000,
                            },
                        }
                    ),
                ]
            )
            + "\n",
            encoding="utf-8",
        )

    def test_import_openclaw_session_command_imports_fixture(self) -> None:
        source_file = self.root / "openclaw-session.jsonl"
        self._write_openclaw_session_fixture(source_file)

        cmd = [
            sys.executable,
            "-m",
            "agent_diary.cli.main",
            "--json",
            "import-openclaw-session",
            "--input-path",
            str(source_file),
            "--source",
            "openclaw-session-import",
            "--source-session-id",
            "session-plain-1",
            "--source-conversation-id",
            "openclaw:session-plain-1",
            "--import-id",
            "import-test-plain",
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
        self.assertFalse(out["dry_run"])
        self.assertEqual(out["resolved_source_session_id"], "session-plain-1")
        self.assertEqual(out["resolved_source_conversation_id"], "openclaw:session-plain-1")
        self.assertEqual(out["source_session_id"], "session-plain-1")
        self.assertEqual(out["source_conversation_id"], "openclaw:session-plain-1")
        self.assertEqual(out["transcript_message_count"], 4)
        self.assertEqual(out["session_chunk_count"], 1)
        self.assertEqual(out["imported_count"], 1)
        self.assertEqual(out["skipped_duplicate_count"], 0)
        self.assertEqual(out["import_id"], "import-test-plain")
        self.assertIn("session=session-plain-1", out["import_label"])
        self.assertIn("conversation=openclaw:session-plain-1", out["import_label"])
        self.assertIsInstance(out["batch_manifest_path"], str)
        self.assertTrue(out["batch_manifest_path"].endswith("import-test-plain.json"))
        self.assertEqual(out["adapter"]["message_count"], 4)
        self.assertEqual(out["session_builder"]["entry_count"], 1)
        self.assertEqual(out["import_result"]["imported_count"], 1)
        self.assertEqual(out["import_result"]["skipped_count"], 0)

        entry_id = out["import_result"]["imported"][0]["entry_id"]
        fetched = fetch_raw_entry(self.paths, {"entry_id": entry_id})
        self.assertEqual(fetched["entry"]["source"], "openclaw-session-import")
        self.assertEqual(fetched["entry"]["metadata"]["ingestion"]["truthful_source"], True)
        self.assertEqual(fetched["entry"]["metadata"]["ingestion"]["import_mode"], "session_jsonl")
        self.assertEqual(fetched["entry"]["metadata"]["ingestion"]["source_session_id"], "session-plain-1")

    def test_import_openclaw_session_command_dry_run_does_not_write_raw_entries(self) -> None:
        source_file = self.root / "openclaw-session-dry-run.jsonl"
        self._write_openclaw_session_fixture(source_file)

        cmd = [
            sys.executable,
            "-m",
            "agent_diary.cli.main",
            "--json",
            "import-openclaw-session",
            "--input-path",
            str(source_file),
            "--source-session-id",
            "session-plain-1",
            "--source-conversation-id",
            "openclaw:session-plain-1",
            "--dry-run",
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
        self.assertTrue(out["dry_run"])
        self.assertEqual(out["resolved_source_session_id"], "session-plain-1")
        self.assertEqual(out["resolved_source_conversation_id"], "openclaw:session-plain-1")
        self.assertEqual(out["transcript_message_count"], 4)
        self.assertEqual(out["session_chunk_count"], 1)
        self.assertEqual(out["imported_count"], 1)
        self.assertEqual(out["skipped_duplicate_count"], 0)
        self.assertIsInstance(out["batch_manifest_path"], str)
        self.assertTrue(out["batch_manifest_path"].endswith(".json"))
        self.assertEqual(out["import_result"]["imported_count"], 1)
        self.assertEqual(out["import_result"]["skipped_count"], 0)
        self.assertEqual(list_entries(self.paths, {"limit": 10, "offset": 0})["items"], [])

    def test_import_openclaw_session_command_skips_duplicate_on_repeat_run(self) -> None:
        source_file = self.root / "openclaw-session-repeat.jsonl"
        self._write_openclaw_session_fixture(source_file)

        base_cmd = [
            sys.executable,
            "-m",
            "agent_diary.cli.main",
            "--json",
            "import-openclaw-session",
            "--input-path",
            str(source_file),
            "--source-session-id",
            "session-plain-1",
            "--source-conversation-id",
            "openclaw:session-plain-1",
        ]
        env = os.environ.copy()
        env["PYTHONPATH"] = str(Path.cwd() / "src")

        first = subprocess.run(
            base_cmd,
            cwd=self.root,
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )
        first_out = json.loads(first.stdout)
        self.assertEqual(first_out["resolved_source_session_id"], "session-plain-1")
        self.assertEqual(first_out["resolved_source_conversation_id"], "openclaw:session-plain-1")
        self.assertEqual(first_out["transcript_message_count"], 4)
        self.assertEqual(first_out["session_chunk_count"], 1)
        self.assertEqual(first_out["imported_count"], 1)
        self.assertEqual(first_out["skipped_duplicate_count"], 0)
        self.assertEqual(first_out["import_result"]["imported_count"], 1)
        self.assertEqual(first_out["import_result"]["skipped_count"], 0)

        second = subprocess.run(
            base_cmd,
            cwd=self.root,
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )
        second_out = json.loads(second.stdout)
        self.assertEqual(second_out["resolved_source_session_id"], "session-plain-1")
        self.assertEqual(second_out["resolved_source_conversation_id"], "openclaw:session-plain-1")
        self.assertEqual(second_out["transcript_message_count"], 4)
        self.assertEqual(second_out["session_chunk_count"], 1)
        self.assertEqual(second_out["imported_count"], 0)
        self.assertEqual(second_out["skipped_duplicate_count"], 1)
        self.assertEqual(second_out["import_result"]["imported_count"], 0)
        self.assertEqual(second_out["import_result"]["skipped_count"], 1)

    def test_import_openclaw_session_command_infers_source_identifiers_when_omitted(self) -> None:
        source_file = self.root / "openclaw-session-infer.jsonl"
        self._write_openclaw_session_fixture(source_file)

        cmd = [
            sys.executable,
            "-m",
            "agent_diary.cli.main",
            "--json",
            "import-openclaw-session",
            "--input-path",
            str(source_file),
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
        self.assertEqual(out["resolved_source_session_id"], "session-plain-1")
        self.assertEqual(out["resolved_source_conversation_id"], "openclaw:session-plain-1")
        self.assertTrue(out["import_id"].startswith("import-openclaw-session-import-session-plain-1-"))
        self.assertIn("session=session-plain-1", out["import_label"])
        self.assertIn("conversation=openclaw:session-plain-1", out["import_label"])
        self.assertEqual(out["import_result"]["imported_count"], 1)
        self.assertEqual(out["import_result"]["skipped_count"], 0)

        entry_id = out["import_result"]["imported"][0]["entry_id"]
        fetched = fetch_raw_entry(self.paths, {"entry_id": entry_id})
        ingestion = fetched["entry"]["metadata"]["ingestion"]
        self.assertEqual(ingestion["source_session_id"], "session-plain-1")
        self.assertEqual(ingestion["source_conversation_id"], "openclaw:session-plain-1")

    def test_import_openclaw_session_command_explicit_ids_override_inferred_defaults(self) -> None:
        source_file = self.root / "openclaw-session-override.jsonl"
        self._write_openclaw_session_fixture(source_file)

        cmd = [
            sys.executable,
            "-m",
            "agent_diary.cli.main",
            "--json",
            "import-openclaw-session",
            "--input-path",
            str(source_file),
            "--source-session-id",
            "manual-session-override",
            "--source-conversation-id",
            "manual-conversation-override",
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
        self.assertEqual(out["resolved_source_session_id"], "manual-session-override")
        self.assertEqual(out["resolved_source_conversation_id"], "manual-conversation-override")
        self.assertIn("session=manual-session-override", out["import_label"])
        self.assertIn("conversation=manual-conversation-override", out["import_label"])
        self.assertTrue(out["import_id"].startswith("import-openclaw-session-import-manual-session-override-"))

        entry_id = out["import_result"]["imported"][0]["entry_id"]
        fetched = fetch_raw_entry(self.paths, {"entry_id": entry_id})
        ingestion = fetched["entry"]["metadata"]["ingestion"]
        self.assertEqual(ingestion["source_session_id"], "manual-session-override")
        self.assertEqual(ingestion["source_conversation_id"], "manual-conversation-override")

    def test_list_imports_returns_recent_manifests_newest_first(self) -> None:
        import_session_jsonl(
            self.paths,
            {
                "path": str(self._write_session_import_fixture("manifest-older.jsonl", "older-1")),
                "import_id": "import-old",
                "source_session_id": "session-old",
                "source_conversation_id": "conv-old",
            },
        )
        import_session_jsonl(
            self.paths,
            {
                "path": str(self._write_session_import_fixture("manifest-newer.jsonl", "newer-1")),
                "import_id": "import-new",
                "source_session_id": "session-new",
                "source_conversation_id": "conv-new",
            },
        )

        result = list_imports(self.paths, {"limit": 10})
        self.assertEqual(result["count"], 2)
        self.assertEqual(result["items"][0]["import_id"], "import-new")
        self.assertEqual(result["items"][1]["import_id"], "import-old")
        self.assertEqual(result["items"][0]["source_session_id"], "session-new")
        self.assertTrue(result["items"][0]["batch_manifest_path"].endswith("import-new.json"))

    def test_list_imports_honors_limit(self) -> None:
        import_session_jsonl(
            self.paths,
            {
                "path": str(self._write_session_import_fixture("manifest-a.jsonl", "a-1")),
                "import_id": "import-a",
                "source_session_id": "session-a",
                "source_conversation_id": "conv-a",
            },
        )
        import_session_jsonl(
            self.paths,
            {
                "path": str(self._write_session_import_fixture("manifest-b.jsonl", "b-1")),
                "import_id": "import-b",
                "source_session_id": "session-b",
                "source_conversation_id": "conv-b",
            },
        )

        result = list_imports(self.paths, {"limit": 1})
        self.assertEqual(result["count"], 1)
        self.assertEqual(len(result["items"]), 1)

    def _write_session_import_fixture(self, filename: str, source_message_id: str) -> Path:
        source_file = self.root / filename
        source_file.write_text(
            json.dumps(
                {
                    "entry_type": "chat_log",
                    "source": "openclaw-session-import",
                    "author_role": "mixed",
                    "created_at": "2026-05-27T10:00:00+00:00",
                    "content": "Bill: hello\nTom: hi",
                    "metadata": {"source_message_id": source_message_id},
                }
            )
            + "\n",
            encoding="utf-8",
        )
        return source_file


if __name__ == "__main__":
    unittest.main()
