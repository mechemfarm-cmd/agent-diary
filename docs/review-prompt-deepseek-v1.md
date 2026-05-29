# Review Prompt - DeepSeek v4 - Agent Diary V1

Review the entire agent-diary repository as a near-term v1 release candidate.

## Project model

This system is built around three separate layers:

1. raw conversation truth
2. work trace of actual agent activity
3. derived artifacts such as compressed memory, conversation briefs, and open-loop analysis

Raw truth remains authoritative.
Work trace is searchable execution provenance.
Derived artifacts are secondary interpretation.

## What I want you to focus on

Be hard on logic and boundaries.

Look for:

- edge-case failures
- incorrect assumptions
- bad dedupe behavior
- brittle import and search logic
- places where work trace and conversation truth could get conflated
- release blockers for an open-source v1

Also evaluate whether the repository would make sense to an outside developer who did not build it with us.

## Constraints

- The goal is not perfection; the goal is a usable and understandable v1.
- Prefer precise fixes over broad rewrites.
- Flag real risk, not theoretical purity complaints.

## Important files

- README.md
- docs/truthful-recurring-ingestion.md
- docs/future-derived-data-model.md
- docs/work-trace-layer-v1.md
- src/agent_diary/service/handlers.py
- src/agent_diary/cli/main.py
- src/agent_diary/cli/openclaw_session_import.py
- src/agent_diary/cli/openclaw_work_trace_import.py
- src/agent_diary/index/repository.py
- src/agent_diary/index/sqlite_index.py
- tests/test_append_entry_slice.py

## Output format

Use this exact structure:

1. Release Blockers
2. High-Risk Logic / Edge Cases
3. Search / Import / Work-Trace Boundary Issues
4. Open-Source Packaging Problems
5. Most Efficient Fix Order

Reference files and explain why each finding matters.
