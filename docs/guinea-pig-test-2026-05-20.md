# Guinea-Pig Test 2026-05-20

## What Was Imported

Imported a first real batch from Bill and Tom's Telegram interaction on 2026-05-20 using:

- source: `telegram-direct-import`
- author_role: `mixed`
- entry_type: `chat_log`

The conversation was chunked into 6 entries instead of one giant transcript:

1. OpenClaw/Tom inclusion in testing and first real-batch discussion
2. Recurring ingestion workflow and context-window trigger idea
3. Emily deployment and Git/Lucy/Emily authority discussion
4. Obsidian / wheel-reinvention concern
5. Backup/deploy review and Git authority follow-up
6. Decision to stop abstract design and begin real testing

## Commands Run

```bash
cd /home/willard/development/agent-diary
PYTHONPATH=src python3 -m agent_diary.cli.main --json import-entries-jsonl --path examples/first_real_test_2026-05-20.jsonl
PYTHONPATH=src python3 -m agent_diary.cli.main --json list-entries --limit 12
PYTHONPATH=src python3 -m agent_diary.cli.main --json produce-open-loops --limit 12
```

## Immediate Result

- 6 real entries imported successfully
- entries appeared correctly in the truth-path listing
- open-loop producer ran successfully
- producer emitted an `analysis:open-loop` artifact attached to the newest imported entry
- loop_count was `0`

## What Seems Trustworthy

- import path works with real, non-synthetic data
- imported entries are visible as raw truth records
- producer lineage window included the intended imported entries
- artifact creation path works even on a real batch

## What Seems Awkward or Weak

- first real batch produced no loops, even though the conversation contained several planning and follow-up themes
- that suggests either:
  - the current chunking muted the heuristic signals
  - or the open-loop producer is still too conservative for realistic mixed conversational text
- attaching the artifact to the newest source entry still feels operationally awkward for discovery

## Useful Next Questions

1. Should imported conversational chunks preserve more explicit action-language instead of paraphrasing?
2. Should the first real batch include a few more clearly unresolved items so signal quality can be judged honestly?
3. Is zero-loop output on this batch actually correct, or is it a miss?
