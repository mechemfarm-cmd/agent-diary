# Agent Diary (Scaffold)

Initial backend/service/CLI scaffold for Agent Diary.

## Scope in this pass

- New Python backend/service/CLI skeleton
- Append-only raw entry storage shape (stubbed)
- SQLite index bootstrap shape (stubbed)
- Local HTTP service with placeholder routes
- Scriptable CLI command surface
- Data directory layout for local development
- Placeholder `ui/` directory only

## Docs

- `docs/ui-v1-surface-contract.md`
- `docs/future-derived-data-model.md`
- `docs/work-trace-layer-v1.md`
- `docs/release-v1-weekend-checklist.md`
- `docs/review-prompt-sonnet-v1.md`
- `docs/review-prompt-deepseek-v1.md`
- `docs/open-loops-producer-v1.md`
- `docs/guinea-pig-testing-quickstart.md`
- `docs/ops-sync-authority.md`

## Quick start

```bash
cd agent-diary
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
agent-diary serve
```

## First Real Testing

Use the minimal owner-testing loop in:

- `docs/guinea-pig-testing-quickstart.md`

It covers:

- local startup
- JSONL entry import
- open-loop producer run
- UI inspection flow

For recurring truthful ingestion from an OpenClaw session export, use the one-command path:

    PYTHONPATH=src python3 -m agent_diary.cli.main --json import-openclaw-session --input-path /path/to/34916b21-e21e-4b82-b062-07fb8d841057.jsonl

Example output:

```json
{
  "dry_run": false,
  "resolved_source_session_id": "session-plain-1",
  "resolved_source_conversation_id": "openclaw:session-plain-1",
  "transcript_message_count": 4,
  "session_chunk_count": 1,
  "imported_count": 1,
  "skipped_duplicate_count": 0,
  "import_id": "import-openclaw-session-import-session-plain-1-20260521T101500Z",
  "batch_manifest_path": "/.../data/imports/batches/import-openclaw-session-import-session-plain-1-20260521T101500Z.json"
}
```

What the top-level summary means:
- `resolved_source_session_id` and `resolved_source_conversation_id` are the identifiers actually used after inference or explicit override.
- `transcript_message_count` is how many canonical transcript messages were built.
- `session_chunk_count` is how many session-import entries were produced.
- `imported_count` is how many raw entries were written.
- `skipped_duplicate_count` is how many source items were skipped by the ledger.
- `import_id` is the batch label recorded in the manifest and ledger.
- `batch_manifest_path` points to the batch manifest file.

Repeat-import behavior:
- the importer records a ledger of prior source items under `data/imports/ledger.json`
- repeated runs skip source items that already have the same stable source key
- `--dry-run` shows the same counts without writing raw entries
