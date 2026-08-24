# AGENTS.md

Canonical instructions for agents in this repository. Assistant-specific files defer to this file.

## Non-Negotiable Invariants

- Run all project commands in Docker. Use `make` targets or `docker compose run --rm test <command>`; never run project Python tooling on the host.
- If `docker-compose.yml` is absent, run `./build.sh` before using Compose.
- Preserve auditability: mutations to audited models and relationship tables must use the logging managers/model methods in `citation/models.py`, and related changes must remain in the same transaction.
- Publication writes must pass `user=request.user` to `PublicationSerializer.save()`. Do not reintroduce `commit=` or bypass its explicit validation/error contract.
- Treat generated migrations as source: after model changes run `make test` or `docker compose run --rm test python /code/make_migrations.py --check`; review and commit any required migration.
- Do not edit historical migrations to repair current models.

## Commands

```text
make build       # build the test image
make up          # start services
make test        # build, start PostgreSQL, migrate, run tests
make clean       # remove local Compose state
```

For one-off Django commands:

```text
docker compose run --rm test python -m django <command>
```

The test settings module is `tests.settings` when invoking Django directly.

## Change Discipline

- Keep changes scoped and preserve public APIs unless the task requires otherwise.
- Use Conventional Commits for commit messages: `type(scope): summary`; mark breaking changes with `!` and do not commit unless explicitly asked.
- Add focused tests for data mutations, audit payloads, endpoint response contracts, and management commands. Run the narrow test first, then `make test`.
- The endpoint layer mixes HTML and JSON renderers; API tests must use the `.json` format suffix where applicable.
- `Note.deleted_on` and other timezone-aware fields require `django.utils.timezone.now()`.
- `PublicationSerializer.save()` raises `TypeError` for caller misuse (missing `user`, invalid `commit`) and `AssertionError` for invalid serializer state or broken create/update postconditions. Keep these distinctions stable.

## Coordination

- Use `.agent/working-memory/`, `.agent/checkpoints/`, and `.agent/handoffs/` only for coordination artifacts, not production code.
- Update the relevant handoff when a milestone changes the next action or test baseline.
