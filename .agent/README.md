# .agent Workspace

This directory stores agent-generated coordination artifacts.

Repository operating baseline:
- standard lifecycle commands live in the root `Makefile`
- one-off project commands run in the `test` container via `docker compose run --rm test <command>`
- current stack is Python 3.12, Django 5.2 LTS, PostgreSQL 18

Use subdirectories as follows:
- `working-memory/`: temporary reasoning notes and active context.
- `checkpoints/`: progress snapshots tied to milestones.
- `handoffs/`: concise transfer notes for a new agent/session.

Do not store production source code in this directory.
