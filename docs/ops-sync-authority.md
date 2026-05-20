# Agent Diary Ops Sync Authority

This repo uses a simple authority model:

- GitHub `origin` (`mechemfarm-cmd/agent-diary`) is the history authority.
- Mac (`/Users/willardmechem/agent-diary`) is the active local dev/test copy.
- Emily and Lucy are synchronized working copies for side-by-side testing.

## Canonical flow

1. Commit on Mac.
2. Push `main` to `origin`.
3. On Emily/Lucy, sync from `origin` (`git fetch && git pull --ff-only`).

## Current host prerequisite

At the moment, Emily and Lucy do not have GitHub SSH key auth configured for `git@github.com`, so direct `git pull` from those hosts fails with `Permission denied (publickey)`.

Until host keys are configured, use temporary mirror sync from Mac to each host (including `.git`) after each push.

## Quick verification

Run on each machine:

```bash
git branch --show-current
git rev-parse HEAD
git status --short
PYTHONPATH=src python3 -m agent_diary.cli.main --help
```
