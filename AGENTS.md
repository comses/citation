# AGENTS.md

This file is the canonical source of truth for AI-agent behavior in this repository.

All other assistant-specific instruction files must defer to this document.

## Command Execution Policy (Required)

- Run all codebase commands inside the project container.
- Preferred pattern: `docker-compose run --rm test <command>`.
- Do not run project Python tooling directly on the host machine.

Bootstrap note:
- If `docker-compose.yml` does not exist yet, run `./build.sh` once to generate config from templates.

Examples:
- Run tests: `docker-compose run --rm test ./run_tests.py`
- Create migrations: `docker-compose run --rm test /code/make_migrations.py -n <migration_name>`
- Django management command: `docker-compose run --rm test python -m django <args>`

## Compressed Project Understanding

- Purpose: Django application for bibliometric metadata ingestion, deduplication, normalization, and citation/reference relationship tracking.
- Core domain: publications, authors, containers, external identifiers, merge workflows, and auditability of data mutations.
- Persistence: PostgreSQL (containerized) with extensive Django migrations in `citation/migrations/`.
- API surface: Django + Django REST Framework via `citation/views.py`, `citation/serializers.py`, and `citation/urls.py`.
- Ingestion pipeline: BibTeX and external metadata lookups (`citation/bibtex/`, `citation/crossref/`, management commands) with dedupe/merge logic.
- Auditing model: mutation logging patterns implemented in `citation/models.py` (log create/update/delete flows and payload capture).
- Test strategy: Django test suite in `tests/`, including end-to-end ingestion/pipeline behavior (`tests/test_pipeline.py`).

## Runtime and Dependency Notes

- Runtime dependency pinning is maintained in `requirements.txt` and `requirements-dev.txt`.
- The container build is defined by `Dockerfile`; compose topology comes from `docker-compose.yml.template` and generated `docker-compose.yml`.
- CI/CD and local usage patterns are Docker-first.

## Working Conventions for Agents

- Keep edits minimal and scoped to the request.
- Preserve existing architecture and naming unless explicitly asked to refactor.
- Prefer deterministic, reproducible command sequences executed in-container.
- When handing off work, write concise status and next actions in `.agent/handoffs/`.

## Agent Workspace Scaffolding

Use `.agent/` for generated coordination artifacts only (not production code):

- `.agent/working-memory/`: short-lived notes, assumptions, and investigation breadcrumbs.
- `.agent/checkpoints/`: milestone snapshots of progress and decision state.
- `.agent/handoffs/`: operator-ready summaries for transfer between agents/sessions.
