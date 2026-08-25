# ADR 0001: Python 3.12 + Django 5.2 LTS Baseline

## Status

Accepted

## Date

2026-08-25

## Context

The citation project needed a supported, maintainable runtime baseline. Prior to this
decision the container image was a Python 3.10-era base with Django pinned to the 4.2
line (`Django>=4.2.20` in the legacy `requirements.txt`), and the codebase still used
pre-modern Django APIs. Django 5.2 is the current long-term-support (LTS) release line,
and Python 3.12 is a mature, widely supported interpreter for it.

## Decision

Standardize on **Python 3.12** and **Django 5.2 LTS** as the supported runtime baseline,
with all validation and debugging performed inside the project's Docker `test` container
(container-first policy).

## Alternatives Considered

- **Django 6.0.x**: rejected because Django 5.2 is the current LTS line; the LTS gives a
  longer support window and a more conservative upgrade surface.
- **Staying on an older Python**: rejected because remaining on an older interpreter
  accumulated near-term technical debt and would make the eventual move to Django 6.x
  harder rather than easier.

## Consequences

- A dependency refresh was required for Python 3.12 wheel availability and Django 5.x
  compatibility. Hard blockers that had to move: `django-extensions`, `django-model-utils`,
  `lxml`, `pandas`, `psycopg2-binary`, and `python-Levenshtein`.
- Legacy API cleanup was required:
  - `django.conf.urls.url` → `path()` / `re_path()`
  - `django.db.backends.postgresql_psycopg2` → `django.db.backends.postgresql`
  - `ugettext_lazy` → `gettext_lazy`
  - model `JSONField` moved from `django.contrib.postgres.fields` to
    `django.db.models.JSONField` (`ArrayField` remains in `django.contrib.postgres.fields`)
- Dependency management now flows through `pyproject.toml` and the committed `uv.lock`
  rather than the historical `requirements.txt` pins.

## Compatibility Notes

- Historical migrations referencing `django.contrib.postgres.fields.jsonb.JSONField` rely
  on Django's migration compatibility layer; migration drift is verified in-container via
  `makemigrations --check`.
- The custom DRF serializer `save()` path in `citation/serializers.py` relies on DRF
  internals and remains the most likely source of subtle breakage across framework
  upgrades; it is a known maintenance risk area.

## Validation Evidence

All gates run inside the Docker `test` container against the Python 3.12 / Django 5.2 /
PostgreSQL 18 baseline:

- `make check` — Django system checks
- `make migrations-check` — migration drift detection
- `make test` — full test suite

## Supersession Path

This ADR is superseded by a future ADR when the project adopts a newer Django line
(for example, Django 6.x). At that point, record the new baseline decision here-by-number
successor, including refreshed dependency constraints and any compatibility findings from
this baseline.
