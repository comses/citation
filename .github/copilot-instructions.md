# Copilot Instructions

Canonical instructions live in `AGENTS.md` at the repository root.

Follow `AGENTS.md` for:
- command execution policy
- project understanding
- agent workflow conventions

Current repo conventions are container-first and Docker-first:
- use `make clean`, `make build`, `make up`, and `make test` for standard local lifecycle actions
- use `docker compose run --rm test <command>` for one-off project commands

If this file conflicts with `AGENTS.md`, `AGENTS.md` takes precedence.
