# Truthful Recurring Ingestion

Raw imported entries are authoritative truth. Derived artifacts are secondary.

For broader product design, treat the canonical transcript contract in
`docs/canonical-conversation-transcript.md` as the transport-independent center
of the ingestion system. Source-specific importers should normalize into that
shape before chunking and import.

## Preferred operator paths

### 1) Telegram direct-chat truth path (preferred current path)

Use `import-telegram-direct` first for real Telegram direct history. It combines:
- inbound Telegram-side logs
- Tom outbound `message.send` events from OpenClaw session files

Example:

    PYTHONPATH=src python3 -m agent_diary.cli.main --json import-telegram-direct \
      --inbound-path ~/.openclaw/agents/main/sessions/sessions.json.telegram-messages.json \
      --sessions-root ~/.openclaw/agents/main/sessions \
      --chat-id 713733361 \
      --source telegram-direct-import

Dry-run first:

    PYTHONPATH=src python3 -m agent_diary.cli.main --json import-telegram-direct \
      --inbound-path ~/.openclaw/agents/main/sessions/sessions.json.telegram-messages.json \
      --sessions-root ~/.openclaw/agents/main/sessions \
      --chat-id 713733361 \
      --source telegram-direct-import \
      --dry-run

That one command:
- reconstructs canonical transcript messages for one Telegram chat
- chunks transcript messages into session-import JSONL
- imports through the normal truthful recurring-ingestion ledger path

### 2) Telegram direct historical bootstrap (preferred backfill path)

Use `backfill-telegram-direct` for historical bootstrap across a trajectory-scoped session set and time window.

Why this is preferred for Telegram direct history:
- inbound truth comes from Telegram-side logs
- outbound truth comes from OpenClaw `message.send` tool results
- trajectory metadata is used only to scope which session files are in-window

Dry-run first:

    PYTHONPATH=src python3 -m agent_diary.cli.main --json backfill-telegram-direct \
      --inbound-path ~/.openclaw/agents/main/sessions/sessions.json.telegram-messages.json \
      --sessions-root ~/.openclaw/agents/main/sessions \
      --trajectories-root ~/.openclaw/agents/main/sessions \
      --session-key 'agent:main:telegram:default:direct:713733361' \
      --chat-id 713733361 \
      --days-back 30 \
      --source telegram-direct-backfill \
      --dry-run

Real run:

    PYTHONPATH=src python3 -m agent_diary.cli.main --json backfill-telegram-direct \
      --inbound-path ~/.openclaw/agents/main/sessions/sessions.json.telegram-messages.json \
      --sessions-root ~/.openclaw/agents/main/sessions \
      --trajectories-root ~/.openclaw/agents/main/sessions \
      --session-key 'agent:main:telegram:default:direct:713733361' \
      --chat-id 713733361 \
      --since 2026-05-01 \
      --until 2026-05-24 \
      --source telegram-direct-backfill

This backfill summary reports:
- discovered vs processed session-file counts
- missing session files
- transcript/session chunk counts
- imported/skipped counts (ledger dedupe)

### 3) OpenClaw session export path

Use `import-openclaw-session` for non-Telegram or plain OpenClaw session-file imports:

    PYTHONPATH=src python3 -m agent_diary.cli.main --json import-openclaw-session \
      --input-path /path/to/34916b21-e21e-4b82-b062-07fb8d841057.jsonl

Dry-run:

    PYTHONPATH=src python3 -m agent_diary.cli.main --json import-openclaw-session \
      --input-path /path/to/34916b21-e21e-4b82-b062-07fb8d841057.jsonl \
      --dry-run

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

If source identifiers are present, importers infer them automatically. Explicit flags still win.

## Use this when...

- `import-telegram-direct`
  - Preferred for routine one-shot or bounded Telegram direct-chat truth ingestion.
  - Input is Telegram inbound log + OpenClaw sessions root + one chat id.

- `backfill-telegram-direct`
  - Preferred for historical Telegram direct bootstrap over a window/session set.
  - Uses trajectory/session-key discovery for scope, then imports through Telegram-direct reconstruction.

- `import-openclaw-session`
  - Use for direct OpenClaw session export ingestion (non-Telegram-direct path).

- `backfill-openclaw-session-key`
  - Use when Telegram inbound logs are unavailable or when you intentionally want plain OpenClaw-session backfill.
  - For Telegram direct history this is lower-fidelity than `backfill-telegram-direct`.

- `build-telegram-direct-transcript`
  - Lower-level debug/dev step to inspect reconstructed canonical transcript without importing.

- `build-transcript-jsonl` + `build-session-jsonl` + `import-session-jsonl`
  - Low-level debugging, custom pipelines, and adapter development.

- `import-entries-jsonl`
  - Dev/demo shortcut for synthetic seed data only (not preferred recurring truth path).

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
- `import-telegram-direct` runs the full Telegram-direct truth path in one command
- `backfill-telegram-direct` runs trajectory-scoped Telegram-direct historical backfill
- `import-openclaw-session` runs the full OpenClaw path in one command
- `build-telegram-direct-transcript` reconstructs canonical Telegram-direct transcript only
- `build-transcript-jsonl` adapts raw exports into canonical transcript messages
- `build-session-jsonl` chunks transcript messages into session-import JSONL
- `import-session-jsonl` imports session-import JSONL through the ledger
- `backfill-openclaw-session-key` discovers many OpenClaw session files from trajectory metadata and imports them as a plain OpenClaw-session backfill

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

Behavior:

- each imported entry gets metadata.ingestion
- each batch writes data/imports/batches/<import_id>.json
- ledger lives at data/imports/ledger.json
- if an item lacks an external source id, the importer falls back to a stable content fingerprint

## Import Batch Inspection Loop

Use import batches as audit/provenance helpers around raw truth, not replacements for raw entries.

CLI review:

    PYTHONPATH=src python3 -m agent_diary.cli.main --json list-imports --limit 20

UI review:

- Timeline now includes a `Recent Imports` list.
- Each row shows `import_id`, `imported_at`, imported/skipped counts, and source ids when present.
- Clicking a batch applies scope to:
  - timeline (`import_id`, conversation when present, `truthful_only=true`)
  - search (same active scope)

Practical operator loop:
1. run import/backfill (`--dry-run` first)
2. review batch summary output (`import_id`, counts, manifest path)
3. inspect recent batches (`list-imports` or UI `Recent Imports`)
4. click/select a batch to inspect scoped entries and run scoped producers/search
5. if you add overlays, check entry detail for derived stale warnings (`overlay_stale` / “May be stale after overlay”) and rerun scoped producers explicitly
