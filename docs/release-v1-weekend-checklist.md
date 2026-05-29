# Release V1 Weekend Checklist

## Goal

Get Agent Diary into a real trial-ready v1 state this weekend, then prepare it for a public GitHub open-source drop.

This is not a polish checklist.
It is a good-enough-to-really-use-and-let-other-developers-run-it checklist.

## V1 Definition

V1 is good enough when all of these are true:

- raw conversation truth is importable and inspectable
- work trace is captureable and searchable
- derived layers are attached and inspectable
- one realistic end-to-end flow works without hand-waving
- README/setup is understandable by a new developer
- known rough edges are named honestly

## Must Finish

### 1. End-to-end trial flow

Run one realistic flow and confirm it works as one system:

1. import truthful conversation data
2. import or backfill OpenClaw work trace
3. run derived producers
4. search and inspect entries, artifacts, and work trace
5. confirm the UI can inspect the result without blocking basic use

This should be treated as the main go/no-go test.

### 2. One more full code pass

Do one more repo-wide pass with Codex/GPT-5.5 focused on:

- obvious logic mistakes
- brittle assumptions
- bad naming or confusing boundaries
- release blockers

This is not the same as more feature work.

### 3. External review pass: Claude Sonnet

Run one full-repo review with Sonnet.

Primary ask:

- code review for bugs, release risk, architecture confusion, and missing documentation

Secondary ask:

- identify where the product language is still too insider/technical

### 4. External review pass: DeepSeek v4

Run one full-repo review with DeepSeek v4.

Primary ask:

- logic and edge-case review
- search/import/work-trace boundary review

Secondary ask:

- identify places where v1 packaging will confuse an outside developer

### 5. Final tune pass in Codex / GPT-5.5

After Sonnet and DeepSeek return:

1. merge overlapping findings
2. ignore weak/generic ones
3. fix the real issues
4. rerun the end-to-end flow

## Should Finish

### README reset

The README still reads like a scaffold.

Before public release, it should explain:

- what Agent Diary is
- the truth model
- what work trace is
- how to run it locally
- one realistic try-it flow
- what is still rough

### License decision

Pick a license before the public GitHub drop.

### Minimal sample/dev flow

Have one path a new developer can follow without guessing:

- install
- serve
- import sample or real bounded data
- run producers
- inspect in UI / CLI

### Honest rough-edges section

List what is still rough instead of pretending it is finished.

Examples:

- UI language still too technical
- work-trace classification is still early
- external-world capture is OpenClaw-session-oriented first
- some search/ranking behavior may still be simplistic

## Nice To Have

- simplify UI wording for normal people
- reduce obvious README/doc duplication
- one short architecture diagram
- one tiny sample dataset or scripted demo path

## Review Questions

Before calling v1 ready, answer these directly:

1. Can Bill use it without needing to remember internal architecture every minute?
2. Can a new developer run it locally without asking us ten questions?
3. Can we explain the difference between truth, work trace, and derived layers in plain language?
4. Does the system behave like one product rather than a set of experiments?

## Recommended Order

1. finish current integration gaps
2. run end-to-end trial flow
3. do Codex repo-wide pass
4. run Sonnet review
5. run DeepSeek review
6. do final Codex tune pass
7. rewrite README/package notes
8. choose license
9. push public v1
