# Agent Diary

A permanent, inspectable memory and work-trace store for one human and one agent.

Separates what was **said** (raw entries), what the agent **did** (work traces), and what the system **inferred** (derived memory) into inspectable layers.

---

## Quick Start

```bash
pip install -e .
agent-diary serve --host 0.0.0.0 --port 8041
```

Then open `http://localhost:8041` in a browser.

---

## For Agents

If you are an autonomous agent integrating with this system, start here:

- **[AGENTS.md](./AGENTS.md)** — What to do, in what order
- **[docs/agent-integration.md](./docs/agent-integration.md)** — Full API contract, JSONL schema, query protocol

## For Humans

If you are the human operator:

- **[docs/user-guide-v1.md](./docs/user-guide-v1.md)** — How to use the UI and interpret the panels
- **[docs/parallel-use-routine.md](./docs/parallel-use-routine.md)** — Running Agent Diary alongside existing memory systems

## Architecture

| Component | What it does | Port |
|-----------|-------------|------|
| API server | REST API + static UI files | 8041 |
| SQLite index | Entry metadata, work traces, memory index | (internal) |
| File store | Raw entry JSON files, artifacts, overlays | (internal) |
| Daily cron | Imports new sessions + work traces from Hermes | (scheduled) |

The API server serves both backend and UI on a single port. No separate static server needed.

## Integration Points

- **Import sessions**: Feed canonical JSONL files into `agent-diary import-session-jsonl`
- **Query memory**: `POST /search_memory` for cross-session recall
- **Query work traces**: `POST /search_work_trace` for operational evidence
- **Browse entries**: `POST /list_entries` with provenance scope filters

See [docs/agent-integration.md](./docs/agent-integration.md) for the full API reference.

## Docs

- `docs/user-guide-v1.md` — Complete operator guide
- `docs/agent-integration.md` — Integration contract for agents
- `docs/parallel-use-routine.md` — Daily parallel-use workflow
- `docs/ui-v1-surface-contract.md` — UI data contracts
- `docs/work-trace-layer-v1.md` — Work trace design
- `docs/release-v1-weekend-checklist.md` — Release preparation

## License

Internal tool. Not for public distribution.