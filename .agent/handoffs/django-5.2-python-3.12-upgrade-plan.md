# Django 5.2 LTS + Python 3.12 Upgrade Handoff

## Summary

- Target platform: Django 5.2 LTS, currently `5.2.12`.
- Runtime target: Python `3.12` in the project container.
- Command policy: run all project commands in-container only, following `AGENTS.md`.
- Upgrade strategy: staged compatibility pass rather than a direct dependency bump.

## Key Decisions

- Use Django `5.2.x` instead of Django `6.0.x` because `5.2` is the current LTS line.
- Still upgrade Python to `3.12` now, even though Django `5.2` supports older versions, to reduce near-term technical debt and smooth a future move to Django `6.x`.
- Keep all validation and debugging inside the `test` container.
- Treat dependency refresh and framework API cleanup as separate phases so failures are easier to attribute.

## Current State

- The repo already has a container-first workflow in `README.md` and `AGENTS.md`.
- The current container build in `Dockerfile` appears Jammy-era and should be assumed to be Python `3.10` unless verified otherwise.
- The codebase currently pins `Django>=4.2.20` in `requirements.txt`.
- The app still contains pre-modern Django APIs that should be updated before or during the LTS bump.

## Confirmed Compatibility Hotspots

- `tests/urls.py`: uses `django.conf.urls.url`, which should be replaced with `path()` or `re_path()`.
- `tests/settings.py`: uses `django.db.backends.postgresql_psycopg2`; modern Django should use `django.db.backends.postgresql`.
- `citation/models.py`: imports `ugettext_lazy`; this should become `gettext_lazy`.
- `citation/admin.py`: imports `ugettext_lazy`; this should become `gettext_lazy`.
- `citation/models.py`: imports `JSONField` from `django.contrib.postgres.fields`; model JSON fields should move to `django.db.models.JSONField` while `ArrayField` remains in `django.contrib.postgres.fields`.
- `citation/serializers.py`: custom `save()` logic explicitly notes reliance on DRF internals, which is a maintenance risk during framework upgrades.
- `requirements.txt`: several packages are old enough to be likely blockers under Python `3.12`, notably `django-extensions==2.1.6`, `django-model-utils==3.1.2`, `psycopg2-binary==2.8.5`, `pandas==0.24.2`.

## Upgrade Phases

### Phase 0: Baseline and Environment Verification

- Generate `docker-compose.yml` with `./build.sh` if missing.
- Record current Python, Django, and dependency versions from inside the container.
- Run the existing test suite to establish a baseline before changes.

Success criteria:
- Current failures are known and recorded.
- Container commands are working reproducibly.

### Phase 1: Python 3.12 Container Upgrade

- Update `Dockerfile` to a Python `3.12` compatible base image or explicitly install Python `3.12` in the container image.
- Revisit OS package installation while touching the image.
- Replace obsolete system package assumptions where needed, especially the PostgreSQL client package line.
- Rebuild the container and verify dependency installation behavior under Python `3.12`.

Success criteria:
- The `test` container builds successfully with Python `3.12`.
- `pip` can resolve and install the project dependency set or clearly identifies blockers.

### Phase 2: Dependency Refresh for Python 3.12 + Django 5.2

- Pin Django to `5.2.12` in `requirements.txt`.
- Upgrade third-party packages to versions compatible with Python `3.12` and Django `5.2`.
- Prioritize Django-adjacent and compiled packages first.

Likely packages to review immediately:
- `Django`
- `djangorestframework`
- `django-extensions`
- `django-model-utils`
- `psycopg2-binary`
- `pandas`
- `scipy`
- `lxml`

Success criteria:
- Container image installs dependencies cleanly on Python `3.12`.
- No dependency resolution dead-ends remain.

### Phase 3: Django API Compatibility Cleanup

- Replace removed/deprecated imports and APIs.
- Update URL routing code to modern Django patterns.
- Move model JSON field usage to modern imports.
- Review any settings behavior that changed across Django versions.

Primary files:
- `tests/urls.py`
- `tests/settings.py`
- `citation/models.py`
- `citation/admin.py`

Success criteria:
- `python -m django check` passes in the container.
- Import-time framework errors are eliminated.

### Phase 4: DRF and Application Behavior Stabilization

- Refactor serializer code that depends on DRF internals if tests or runtime behavior break under the upgraded stack.
- Re-test view flows that mutate request data or mix DRF rendering with Django redirects/messages.
- Validate end-to-end ingestion and dedupe flows, especially the BibTeX pipeline tests.

Primary files:
- `citation/serializers.py`
- `citation/views.py`
- `tests/test_pipeline.py`
- `tests/test_serializers.py`
- `tests/test_views.py`

Success criteria:
- Tests pass or failures are narrowed to explicit, understood behavior changes.
- No silent serializer or request parsing regressions remain.

### Phase 5: Final Validation and Documentation

- Run full validation in the upgraded container.
- Update docs if command examples, runtime requirements, or setup expectations changed.
- Capture residual risks and deferred cleanup in a follow-up handoff.

Success criteria:
- Full suite is green or remaining failures are documented with root causes.
- The repo documents Python `3.12` and Django `5.2` as the new supported baseline.

## Recommended Command Sequence

Run all commands from the repository root and inside the project container unless the command is the bootstrap script.

Bootstrap if needed:

```bash
./build.sh
```

Baseline and verification:

```bash
docker-compose run --rm test python --version
docker-compose run --rm test python -c "import django; print(django.get_version())"
docker-compose run --rm test ./run_tests.py
docker-compose run --rm test python -m django check
docker-compose run --rm test python -m django makemigrations --check --dry-run
```

After container and dependency changes:

```bash
docker-compose build test
docker-compose run --rm test python --version
docker-compose run --rm test python -m django check
docker-compose run --rm test ./run_tests.py
```

## Risks

- Python `3.12` may force larger dependency jumps than Django `5.2` alone would require.
- Old compiled/runtime libraries may fail to install cleanly without additional version bumps.
- The custom DRF serializer save path may break in non-obvious ways and require a real refactor rather than a small compatibility edit.
- Historical migrations that reference older field classes may need careful handling if import paths change.

## Suggested First Implementation Slice

1. Verify the current container Python version and dependency install behavior.
2. Update the container to Python `3.12` and get the image building.
3. Refresh dependency pins until the container installs cleanly.
4. Apply the low-risk Django compatibility changes in `tests/urls.py`, `tests/settings.py`, `citation/models.py`, and `citation/admin.py`.
5. Run `django check`, migration validation, and the full test suite in-container.

## Status

## Implementation Status (Phase 1–3 Complete)

### Done

- **Dockerfile** updated to `python:3.12-slim` base; removed outdated xenial PostgreSQL APT repo and `python3-dev`/`python3-pip` (no longer needed in an official Python image); modernized `pip` invocation; cleaned apt lists.
- **requirements.txt** pinned to `Django==5.2.12`; updated hard blockers for Python 3.12 / Django 5.2 compatibility:
	- `django-extensions>=3.2.3` (was `==2.1.6`, did not support Django 5.x)
	- `django-model-utils>=4.5.0` (was `==3.1.2`, did not support Django 5.x)
	- `lxml>=5.2.0` (was `==4.9.1`, no Python 3.12 wheel)
	- `pandas>=2.2.0` (was `==0.24.2`, did not support Python 3.12)
	- `psycopg2-binary>=2.9.9` (was `==2.8.5`, Python 3.12 reliability)
	- `python-Levenshtein>=0.25.0` (was `>=0.12,<0.13`, upper bound blocked install)
- **tests/urls.py** migrated from `django.conf.urls.url` to `django.urls.re_path`.
- **tests/settings.py** updated `ENGINE` from `django.db.backends.postgresql_psycopg2` to `django.db.backends.postgresql`.
- **citation/models.py** migrated `JSONField` import from `django.contrib.postgres.fields` to `django.db.models`; changed `ugettext_lazy` to `gettext_lazy`.
- **citation/admin.py** changed `ugettext_lazy` to `gettext_lazy`.
- All edited Python files pass syntax validation.

### Pending (requires Docker Desktop WSL integration to be enabled)

- Container build: `docker-compose build test`
- Baseline runtime check: `docker-compose run --rm test python --version`
- Framework check: `docker-compose run --rm test python -m django check`
- Migration dry-run: `docker-compose run --rm test python -m django makemigrations --check --dry-run`
- Full test suite: `docker-compose run --rm test ./run_tests.py`

### Known Remaining Risks

- `django-autofixture` has been removed from `requirements-dev.txt` and replaced in tests with direct model creation to avoid legacy packaging failures.
- `bleach==3.3.0` is old but pure-Python; it may surface deprecation warnings or fail if any Python 3.12 stdlib APIs it relies on changed. Watch for it during the test run.
- The custom `save()` method in `citation/serializers.py` copies DRF internals and is the most likely source of subtle breakage. It is deferred to Phase 4 per the upgrade plan.
- Historical migrations reference `django.contrib.postgres.fields.jsonb.JSONField`; Django should handle these via its migration compatibility layer, but verify with `makemigrations --check` in-container.
