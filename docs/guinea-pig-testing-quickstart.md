# Guinea-Pig Testing Quickstart

This is the smallest practical operator loop for truthful recurring ingestion and scoped inspection.
Raw imported entries are authoritative. Derived artifacts are secondary.

## 1) Setup

```bash
cd /Users/willardmechem/agent-diary
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## 2) Start the service

```bash
PYTHONPATH=src python3 -m agent_diary.cli.main serve --host 127.0.0.1 --port 8041
```

## 3) Historical bootstrap first (truth-first path)

Dry-run first:

```bash
PYTHONPATH=src python3 -m agent_diary.cli.main --json backfill-telegram-direct \
  --inbound-path ~/.openclaw/agents/main/sessions/sessions.json.telegram-messages.json \
  --sessions-root ~/.openclaw/agents/main/sessions \
  --trajectories-root ~/.openclaw/agents/main/sessions \
  --session-key 'agent:main:telegram:default:direct:713733361' \
  --chat-id 713733361 \
  --source telegram-direct-backfill \
  --days-back 30 \
  --dry-run
```

Then run without dry-run:

```bash
PYTHONPATH=src python3 -m agent_diary.cli.main --json backfill-telegram-direct \
  --inbound-path ~/.openclaw/agents/main/sessions/sessions.json.telegram-messages.json \
  --sessions-root ~/.openclaw/agents/main/sessions \
  --trajectories-root ~/.openclaw/agents/main/sessions \
  --session-key 'agent:main:telegram:default:direct:713733361' \
  --chat-id 713733361 \
  --source telegram-direct-backfill \
  --since 2026-05-01 \
  --until 2026-05-24
```

Expect summary fields including:
- `discovered_session_file_count`
- `processed_session_file_count`
- `missing_session_files`
- `transcript_message_count`
- `session_chunk_count`
- `imported_count`
- `skipped_duplicate_count`
- `import_id`
- `batch_manifest_path`

## 4) Routine bounded import after bootstrap

Use one-shot `import-telegram-direct` for ongoing bounded pulls after initial historical backfill:

```bash
PYTHONPATH=src python3 -m agent_diary.cli.main --json import-telegram-direct \
  --inbound-path ~/.openclaw/agents/main/sessions/sessions.json.telegram-messages.json \
  --sessions-root ~/.openclaw/agents/main/sessions \
  --chat-id 713733361 \
  --source telegram-direct-import
```

## 5) Review import batches before derived regeneration

```bash
PYTHONPATH=src python3 -m agent_diary.cli.main --json list-imports --limit 20
```

Confirm the latest batch has expected:
- `import_id`
- `imported_at`
- `imported_count`
- `skipped_duplicate_count`
- source ids when present

## 6) Apply scope and run scoped derived producers

Use the batch id (and optionally conversation id) from step 5:

```bash
PYTHONPATH=src python3 -m agent_diary.cli.main --json produce-open-loops \
  --import-id <IMPORT_ID> \
  --truthful-only \
  --limit 200
```

```bash
PYTHONPATH=src python3 -m agent_diary.cli.main --json produce-conversation-briefs \
  --import-id <IMPORT_ID> \
  --truthful-only \
  --limit 200
```

```bash
PYTHONPATH=src python3 -m agent_diary.cli.main --json produce-compressed-memory \
  --import-id <IMPORT_ID> \
  --truthful-only \
  --limit 200
```

## 7) Dev/demo shortcut only: synthetic seed import

Use this only when you need quick local UI/demo data, not as the preferred recurring truth path.

```bash
PYTHONPATH=src python3 -m agent_diary.cli.main --json import-entries-jsonl --path examples/guinea_pig_seed.jsonl
```

## 8) Open UI and inspect

In a second terminal:

```bash
cd /Users/willardmechem/agent-diary/ui
python3 -m http.server 5173
```

Open `http://127.0.0.1:5173`.

Testing path:
1. Use `Recent Imports` in Timeline to select the latest import batch (auto-applies import scope).
2. Confirm timeline and search now stay inside that batch scope.
3. Use timeline scope controls when you need manual overrides (`source_conversation_id`, `import_id`, `truthful_only`).
4. Open entries in timeline and confirm raw entry text is primary in detail view.
5. Expand `Artifacts (secondary)`.
6. Confirm derived artifacts (brief/memory/open-loop) are secondary layers attached to raw truth.
7. Click supporting entry ids and confirm navigation to raw entries.
8. Add an overlay on an entry and confirm stale-derived warning appears where applicable (`May be stale after overlay`).
9. Rerun the relevant scoped producer explicitly (`produce-open-loops`, `produce-conversation-briefs`, and/or `produce-compressed-memory`), then re-open entry detail to confirm refreshed derived artifacts.

## 9) Useful one-liners

List entries:

```bash
PYTHONPATH=src python3 -m agent_diary.cli.main --json list-entries --limit 20
```

List entries scoped to one import:

```bash
PYTHONPATH=src python3 -m agent_diary.cli.main --json list-entries \
  --import-id <IMPORT_ID> \
  --truthful-only \
  --limit 50
```

Scoped search:

```bash
PYTHONPATH=src python3 -m agent_diary.cli.main --json search-memory \
  --query "browser route" \
  --import-id <IMPORT_ID> \
  --truthful-only \
  --limit 20
```

Fetch one entry with artifacts:

```bash
PYTHONPATH=src python3 -m agent_diary.cli.main --json fetch-raw-entry --entry-id <ENTRY_ID> --include-artifacts
```

Optional lower-level debug path (not the preferred operator path):

```bash
PYTHONPATH=src python3 -m agent_diary.cli.main --json build-telegram-direct-transcript \
  --inbound-path ~/.openclaw/agents/main/sessions/sessions.json.telegram-messages.json \
  --sessions-root ~/.openclaw/agents/main/sessions \
  --chat-id 713733361 \
  --output-path /tmp/telegram_direct_transcript.jsonl
```
