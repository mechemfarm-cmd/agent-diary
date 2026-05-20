# Agent Diary UI Shell (V1 Minimal)

This is a minimal local UI shell implementing the v1 surface contract.

## What it covers

- Timeline list from `list_entries`
- Entry detail from `fetch_entry_detail`
- Memory search from `search_memory`
- Click-through from search hit to entry detail via `entry_id`
- Raw entry content shown as primary body
- Artifacts shown as secondary metadata
- `analysis:open-loop` artifacts rendered in the secondary artifact section with:
  - title
  - summary
  - strength/confidence
  - clickable supporting entry ids (navigates to raw entry detail)
- Lightweight local UI state persistence (`localStorage`) for:
  - selected entry
  - list paging (`offset`, `limit`)
  - current search query
  - selected search-hit entry
- Lightweight URL state for reopenable/deep-link context:
  - `?entry=<entry_id>`
  - `?q=<search_query>`
  - `?offset=<timeline_offset>`
  - URL state is restored first; localStorage is fallback when URL has no state.

## Run locally

Terminal 1 (backend service):

```bash
cd /Users/willardmechem/agent-diary
PYTHONPATH=src python3 -m agent_diary.cli.main serve --host 127.0.0.1 --port 8041
```

Terminal 2 (static UI server):

```bash
cd /Users/willardmechem/agent-diary/ui
python3 -m http.server 5173
```

Open:

- http://127.0.0.1:5173

If needed, set `API Base` in the header (default: `http://127.0.0.1:8041`).

## Manual accessibility check (lightweight)

1. Use `Tab` from the top and confirm visible focus is clear on API controls, timeline buttons, search controls, and artifact summary.
2. In timeline or search results, use `ArrowUp`/`ArrowDown` plus `Home`/`End` to move between result buttons.
3. Press `Enter` on a focused timeline/search item and confirm entry detail loads and focus moves to the diary body.
4. Use the “Skip to diary entry” link at top to jump directly to the raw entry body.
5. If an entry has `analysis:open-loop` artifacts, expand “Artifacts (secondary)” and verify loop cards render as derived interpretation with supporting-entry navigation.

No automated UI accessibility tests are included in this shell pass.
