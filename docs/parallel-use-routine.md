# Simple Parallel-Use Routine

This is the smallest practical routine for using Agent Diary beside normal Hermes memory.

Principle:
- Hermes memory remains the primary working memory for now.
- Agent Diary runs in parallel as the inspectable truth, work-trace, and derived-recall layer.
- **Daily cron import** (`hermes-to-diary.sh`) imports new Hermes sessions automatically once per day.

## Architecture (current)

| Component | How it runs |
|-----------|-------------|
| API + UI server | Single process: `agent-diary serve --host 0.0.0.0 --port 8041` |
| UI files | Served from the API server (no separate static server) |
| Auto-import | Daily cron job via `~/.hermes/scripts/hermes-to-diary.sh` |
| Tailscale URL | `http://100.101.169.71:8041/` |
| Home WiFi URL | `http://192.168.178.40:8041/` |

The UI auto-detects the API server from `window.location.origin` — no URL configuration needed.

## When to use it

Open the UI when you want:
- verbatim recall of a conversation
- scoped inspection of a real conversation block
- searchable work trace
- open-loop review
- raw-entry trust verification

## How the daily pipeline works

1. A cron job runs `hermes-to-diary.sh` once per day
2. It queries `~/.hermes/state.db` for sessions not yet imported
3. For each new session, it extracts user + assistant messages
4. Imports them as diary entries via `agent-diary import-session-and-analyze`
5. This automatically generates conversation briefs, compressed memory, and open loops
6. Markers in `data/hermes-import-tracker/` prevent double-importing

## Manual import (if needed)

If you want to import immediately rather than waiting for the daily cron:

```bash
cd /home/willard/development/agent-diary
bash ~/.hermes/scripts/hermes-to-diary.sh
```

Or trigger the cron job from the agent:

```
Run the daily import now
```

## Use the UI as the inspection surface

Open in any browser:

```
http://100.101.169.71:8041/
```

In the UI:
- the timeline shows all entries with work-trace badges when agent work exists
- the right panel has **3 tabs**: Derived, Annotations, Actions
- select an import batch from `Recent Imports` to scope the view
- keep `Truthful only` on for clean import-bounded view
- inspect raw entries in the center pane
- inspect open loops, brief, and compressed memory in the Derived tab
- add overlays in the Annotations tab
- refresh derived layers in the Actions tab

## Trial behavior

During the trial:
- use Hermes memory normally for fast live work
- use Agent Diary when you need:
  - verbatim recall
  - scoped inspection of a real conversation block
  - searchable work trace
  - open-loop review

## What counts as success

This parallel routine is working if:
- recent chat truth lands cleanly via daily cron
- recent work trace lands cleanly
- derived layers attach without drama
- UI inspection is good enough that Bill does not need to remember repo internals every minute

## Current known rough edges

- Work trace import is still OpenClaw-session-shaped rather than fully generalized.
- The UI right panel tabs are new; tab selection is not yet persisted across page reloads.
- No mobile-responsive layout below 680px (functional but cramped).
