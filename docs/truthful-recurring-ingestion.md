# Truthful Recurring Ingestion

Use `import-entries-jsonl` only for one-off seed data and synthetic corpus tests.
For real recurring conversation ingestion from OpenClaw, use `import-openclaw-session`.

For broader product design, treat the canonical transcript contract in
`docs/canonical-conversation-transcript.md` as the transport-independent center
of the ingestion system. Source-specific importers should normalize into that
shape before chunking and import.

Recommended path:

    PYTHONPATH=src python3 -m agent_diary.cli.main --json import-openclaw-session \
      --input-path /path/to/34916b21-e21e-4b82-b062-07fb8d841057.jsonl

That one command:
- adapts the raw OpenClaw export into canonical transcript messages
- chunks transcript messages into session-import JSONL
- imports through the truthful recurring-ingestion path

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

Top-level summary fields mean:
- `resolved_source_session_id` and `resolved_source_conversation_id` are the identifiers actually used after inference or explicit override
- `transcript_message_count` is how many canonical transcript messages were built
- `session_chunk_count` is how many session-import entries were produced
- `imported_count` is how many raw entries were written
- `skipped_duplicate_count` is how many source items were skipped by the ledger
- `import_id` is the batch label recorded in the manifest and ledger
- `batch_manifest_path` points to the batch manifest file

Repeat-import behavior:
- the importer records a ledger of prior source items under `data/imports/ledger.json`
- repeated runs skip source items that already have the same stable source key
- `--dry-run` shows the same counts without writing raw entries

If the source export already carries session/conversation identifiers, `import-openclaw-session` infers them automatically. Explicit flags still win.

Input format:

- JSONL, one entry per line
- same required entry fields as append-entry
- prefer metadata.source_item_id or metadata.source_message_id when available

Canonical transcript-message schema:

- JSONL, one message per line
- required fields:
  - message_id
  - created_at
  - author_role
  - speaker
  - content
- optional:
  - metadata object

CLI help at a glance:
- `build-transcript-jsonl` adapts raw exports into canonical transcript messages
- `build-session-jsonl` chunks transcript messages into session-import JSONL
- `import-session-jsonl` imports session-import JSONL through the ledger
- `import-openclaw-session` runs the full OpenClaw path in one command
- `backfill-openclaw-session-key` discovers many OpenClaw session files from trajectory metadata and imports them as a controlled backfill

Controlled backfill example:

    PYTHONPATH=src python3 -m agent_diary.cli.main --json backfill-openclaw-session-key \
      --session-key 'agent:main:telegram:default:direct:713733361' \
      --trajectories-root ~/.openclaw/agents/main/sessions \
      --days-back 30 \
      --source telegram-direct-bootstrap \
      --dry-run

Notes:
- use `--dry-run` first to inspect how many session files and transcript messages will be imported
- this path uses trajectory `session.started` records as the authority for which session files belong to a session key
- repeated runs still dedupe through the normal import ledger

Plain OpenClaw session-log adapter notes:

- only top-level `type == "message"` records are adapted
- only nested `message.role` values of `user` and `assistant` are kept
- user content is taken directly from the string body
- assistant content is taken only from nested `type == "text"` items
- tool-call-only assistant records are skipped
- useful identity is preserved from `id`, `parentId`, `timestamp`, nested message timestamp, and session header fields when present

Behavior:

- each imported entry gets metadata.ingestion
- each batch writes data/imports/batches/<import_id>.json
- ledger lives at data/imports/ledger.json
- if an item lacks an external source id, the importer falls back to a stable content fingerprint
