# Review Prompt - Claude Sonnet - Agent Diary V1

You are reviewing the entire agent-diary repository for a near-term v1 release.

## What this project is

Agent Diary is a local-first memory/diary system for agent work.

Its core model is:

1. raw conversation truth
2. work trace of what the agent actually did
3. derived interpretation layers such as compressed memory, conversation briefs, and open loops

Raw truth is authoritative.
Work trace is execution provenance.
Derived artifacts are secondary.

## What I want from you

Do a serious code-and-product review, not a marketing brainstorm.

Prioritize:

- bugs
- release risks
- confusing architecture seams
- brittle assumptions
- missing documentation
- places where the UI or docs use overly technical or insider language

## Important constraints

- Do not suggest sweeping rewrites unless the current design is genuinely unsalvageable.
- Assume the goal is to ship a usable v1 this weekend.
- Prefer surgical fixes and packaging improvements over abstract redesign.
- Distinguish clearly between:
  - must fix before v1
  - should fix soon after
  - acceptable rough edges

## Files to pay special attention to

- README.md
- docs/truthful-recurring-ingestion.md
- docs/future-derived-data-model.md
- docs/work-trace-layer-v1.md
- src/agent_diary/service/handlers.py
- src/agent_diary/cli/main.py
- src/agent_diary/cli/openclaw_session_import.py
- src/agent_diary/cli/openclaw_work_trace_import.py
- src/agent_diary/index/repository.py
- tests/test_append_entry_slice.py
- ui/

## Output format

Use this exact structure:

1. Must Fix Before V1
2. Should Fix Soon After
3. Acceptable Rough Edges
4. Language / UX Simplification Opportunities
5. Fastest Path To A Credible Public GitHub V1

Be concrete. Reference files and behaviors.
