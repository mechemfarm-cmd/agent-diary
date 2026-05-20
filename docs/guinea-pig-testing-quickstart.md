# Guinea-Pig Testing Quickstart

This is the smallest practical loop for first real owner testing.

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

## 3) Seed a small real-ish batch

Use bundled sample:

```bash
PYTHONPATH=src python3 -m agent_diary.cli.main --json import-entries-jsonl --path examples/guinea_pig_seed.jsonl
```

Or create your own JSONL file with one entry per line:

```json
{"entry_type":"manual_note","source":"cli","author_role":"human","created_at":"2026-05-26T12:00:00+00:00","content":"...","metadata":{}}
```

Required fields per line:
- `entry_type`
- `source`
- `author_role`
- `content`
- `created_at`

## 4) Run open-loop producer

```bash
PYTHONPATH=src python3 -m agent_diary.cli.main --json produce-open-loops --limit 20
```

## 5) Open UI and inspect

In a second terminal:

```bash
cd /Users/willardmechem/agent-diary/ui
python3 -m http.server 5173
```

Open `http://127.0.0.1:5173`.

Testing path:
1. Open seeded entries in timeline.
2. Confirm raw entry text is primary in detail view.
3. Expand `Artifacts (secondary)`.
4. Confirm `analysis:open-loop` cards appear with title/summary/strength.
5. Click supporting entry ids and confirm navigation to raw entries.

## 6) Useful one-liners

List entries:

```bash
PYTHONPATH=src python3 -m agent_diary.cli.main --json list-entries --limit 20
```

Fetch one entry with artifacts:

```bash
PYTHONPATH=src python3 -m agent_diary.cli.main --json fetch-raw-entry --entry-id <ENTRY_ID> --include-artifacts
```
