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
- `docs/open-loops-producer-v1.md`
- `docs/guinea-pig-testing-quickstart.md`

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
