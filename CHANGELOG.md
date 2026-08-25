# Changelog

## 1.0.0 - 2026-08-25

### Added

- Container-first development and release verification workflow.
- Explicit Django system-check and migration-drift gates.
- Focused serializer, endpoint, and management-command test coverage.
- Sphinx documentation migrated from reStructuredText to MyST Markdown.
- Architecture decision record index with the Python 3.12 / Django 5.2 LTS baseline decision (`docs/source/adr/`).
- Documentation build gate in CI and a documentation ownership map in the README.

### Changed

- Established Python 3.12, Django 5.2, and PostgreSQL 18 as the supported runtime baseline.
- Publication serializer mutations now enforce explicit user and commit contracts.
- Docker dependency installation now uses the committed `uv.lock` file.
- Package metadata now identifies citation as Production/Stable.
