# Simple Parallel-Use Routine

This is the smallest practical routine for using Agent Diary beside normal OpenClaw memory.

Principle:
- OpenClaw memory remains the primary working memory for now.
- Agent Diary runs in parallel as the inspectable truth, work-trace, and derived-recall layer.

## When to run it

Run this loop:
- after a meaningful Bill/Tom conversation block
- after a coding/debugging stretch you want preserved
- or at least once per day during the trial

## 1. Make sure the local app is up on Emily

Backend:

```bash
cd /home/willard/development/agent-diary
PYTHONPATH=src python3 -m agent_diary.cli.main serve --host 127.0.0.1 --port 8041
```

UI:

```bash
cd /home/willard/development/agent-diary
python3 -m http.server 5173 --bind 127.0.0.1 --directory ui
```

## 2. Import recent Telegram direct-chat truth

For ongoing use, prefer the one-shot bounded import:

```bash
cd /home/willard/development/agent-diary
PYTHONPATH=src python3 -m agent_diary.cli.main --json import-telegram-direct \
  --inbound-path /home/willard/.openclaw/agents/main/sessions/sessions.json.telegram-messages.json \
  --sessions-root /home/willard/.openclaw/agents/main/sessions \
  --chat-id 713733361 \
  --source telegram-direct-import
```

This is the normal truth import path for ongoing direct-chat use.

## 3. Import recent work trace

For the same session key, pull in recent OpenClaw work trace:

```bash
cd /home/willard/development/agent-diary
PYTHONPATH=src python3 -m agent_diary.cli.main --json backfill-openclaw-work-trace-session-key \
  --session-key 'agent:main:telegram:default:direct:713733361' \
  --trajectories-root /home/willard/.openclaw/agents/main/sessions \
  --days-back 1
```

If a day-back window is too broad later, tighten it with `--since` / `--until`.

## 4. Find the latest import batch

```bash
cd /home/willard/development/agent-diary
PYTHONPATH=src python3 -m agent_diary.cli.main --json list-imports --limit 5
```

Use the newest `import_id` from the result.

## 5. Refresh derived layers for that import

```bash
cd /home/willard/development/agent-diary
PYTHONPATH=src python3 -m agent_diary.cli.main --json produce-open-loops \
  --import-id <IMPORT_ID> \
  --truthful-only \
  --limit 200
```

```bash
cd /home/willard/development/agent-diary
PYTHONPATH=src python3 -m agent_diary.cli.main --json produce-conversation-briefs \
  --import-id <IMPORT_ID> \
  --truthful-only \
  --limit 200
```

```bash
cd /home/willard/development/agent-diary
PYTHONPATH=src python3 -m agent_diary.cli.main --json produce-compressed-memory \
  --import-id <IMPORT_ID> \
  --truthful-only \
  --limit 200
```

## 6. Use the UI as the inspection surface

Open:

```text
http://127.0.0.1:5173
```

In the UI:
- select the latest import in `Recent Imports`
- keep `Truthful only` on when you want the clean import-bounded view
- inspect raw entries in the center pane
- inspect open loops, brief, and compressed memory on the right
- use search when you need recall, but treat raw entry detail as source of truth

## 7. Trial behavior

During the trial:
- use OpenClaw memory normally for fast live work
- use Agent Diary when you need:
  - verbatim recall
  - scoped inspection of a real conversation block
  - searchable work trace
  - open-loop review

## 8. What counts as success

This parallel routine is working if:
- recent chat truth lands cleanly
- recent work trace lands cleanly
- derived layers attach without drama
- UI inspection is good enough that Bill does not need to remember repo internals every minute

## 9. Current rough edges

- UI is usable, but still a little dense in the left navigation column.
- The backend and UI are still served separately.
- Work trace import is usable, but still OpenClaw-session-shaped rather than fully generalized.
