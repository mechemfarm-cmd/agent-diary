# Agent Diary UI V1 Surface Contract

## Purpose
Define the first human-facing, Daylog-like UI surface without implementing frontend code.

## Core screens (v1)

1. Diary/Timeline view
2. Entry Detail view
3. Minimal Search surface
4. Optional Artifact/Meta side panel (collapsed by default)

## Screen behavior

### 1) Diary/Timeline view
Primary job: browsing diary entries as human-readable raw memory records.

Show per row:
- `created_at`
- `entry_type`
- `source`
- `author_role`
- `preview` (compact raw-entry preview)

Visual priority:
- Primary: diary entry list rows (raw-entry based)
- Secondary: entry metadata chips (`entry_type`, `source`, `author_role`)

Data source:
- `list_entries(limit, offset)`

### 2) Entry Detail view
Primary job: show one authoritative raw entry in full.

Show:
- full raw entry body from `raw_entry.content` (primary text block)
- entry header metadata (`created_at`, `entry_type`, `source`, `author_role`)
- attached artifacts as secondary supporting items (metadata-first list)

Visual priority:
- Primary: `raw_entry` body
- Secondary: artifact list/meta and truth-model labeling

Data source:
- `fetch_entry_detail(entry_id)`
- fallback/verification path: `fetch_raw_entry(entry_id)` when needed

### 3) Minimal Search surface
Primary job: quickly locate likely relevant entries via compressed-memory recall, then open truth.

Show per hit:
- `match_text` snippet
- `indexed_at`
- link target (`entry_id`)

Interaction rule:
- Clicking a hit opens Entry Detail for the same `entry_id`.
- Search results are navigation aids, not diary-body replacements.

Data source:
- `search_memory(query, limit, filters)`

### 4) Optional Artifact/Meta panel
Behavior:
- Hidden/collapsed by default on Entry Detail.
- Expands to show artifact metadata from `fetch_entry_detail(...).artifacts`.
- Never replaces or displaces raw body as the primary reading surface.

## Interaction rules

1. Browse flow:
- User lands on Timeline.
- Scroll/paginate with `list_entries`.

2. Open entry flow:
- Selecting a row opens Entry Detail for that `entry_id`.

3. Memory-hit-to-truth flow:
- User enters search query.
- UI shows compressed-memory hits.
- Selecting a hit navigates to Entry Detail (`entry_id`) and reads raw truth.

4. Overlay/edit mental model (not implemented yet):
- Raw entry is immutable source record.
- Human corrections/annotations should appear as overlays, not destructive edits.

## API dependency map

- Timeline: `list_entries`
- Entry Detail: `fetch_entry_detail`
- Search surface: `search_memory`
- Deep truth fetch (optional fallback): `fetch_raw_entry`

## Explicit non-goals (v1 UI)

- No admin-console/system-management surface.
- No presentation where compressed-memory artifact text is the main diary body.
- No multi-user controls, role management, sync admin, or deployment controls.

## Tiny API clarification for later

- `list_entries` currently builds `entry_type` and `preview` by reading raw files via indexed paths. Later, backend may optionally persist `entry_type` and a preview cache in SQLite for faster timeline reads, but the truth model should remain unchanged.
