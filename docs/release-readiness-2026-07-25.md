# Stable Release Readiness and Future Work Priorities

Date: 2026-07-25

## Current release readiness status

Overall status: ready for a stable release candidate with passing tests and warning surface narrowed to known Django checks.

Evidence gathered from containerized workflow:
- Command: `make test`
- Result: 40 tests passed, 0 failures
- Runtime: ~73 seconds including image build and migration setup

Notable warnings observed during test run:
- Django `models.W042` default primary key warnings across legacy models
- Django `staticfiles.W004` missing static dir in test settings

Warnings resolved in this release prep:
- Python `SyntaxWarning` in DOI regex parsing and sanitization paths

## Release checklist (next stable)

1. Freeze version and changelog
- Bump `project.version` in `pyproject.toml` from `0.0.1` to the target stable version.
- Add release notes summarizing bug fixes, dependency baseline, and migration expectations.

2. Dependency lock and reproducibility
- Run `make lock` and commit `uv.lock` if dependency set changed.
- Rebuild images with `make build` to verify lockfile compatibility.

3. Verification gates
- Run `make test`.
- Run `docker compose run --rm test python -m django check`.
- Run `docker compose run --rm test python -m django makemigrations --check --dry-run`.

4. Publish dry-run and release
- Build package artifacts in container (`uv build`).
- Publish with `PYPI_TOKEN=... make publish`.

5. Post-release validation
- Install from published index in a clean environment.
- Run a minimal integration path (migrate, ingest sample bibtex, query API endpoint).

## Prioritized future work

P0 (before or during next stable cycle)
- Resolve framework warnings that can mask real regressions:
  - Set `DEFAULT_AUTO_FIELD` strategy and document migration policy for legacy IDs.
  - Decide whether to keep `AutoField` intentionally or migrate to `BigAutoField`.
- Add release automation guardrails:
  - CI gate for `django check` and migration drift (`makemigrations --check --dry-run`).

P1 (near-term quality and maintainability)
- Add warning budget in CI:
  - Fail on new Python runtime warnings in parsing and ingestion modules.
- Create a small smoke test target for package-install + startup verification.
- Improve migration data-task observability (structured logging for category backfills and URL pattern setup).

P2 (medium-term improvements)
- Expand ingestion robustness tests:
  - More malformed citation/ref inputs and DOI edge cases.
- Introduce performance baseline tests for dedupe/merge paths with realistic dataset sizes.
- Add release playbook automation (single command that runs lock, checks, tests, publish preflight).

## Suggested ownership map

- Platform/Release: versioning, publish, CI gate expansion
- Data model maintainers: `DEFAULT_AUTO_FIELD` decision and migration strategy
- Ingestion maintainers: parser warning budget and edge-case tests

## Exit criteria for the next stable release

- Test suite green in containerized workflow
- No unreviewed warnings in release logs
- Migration drift check passes
- Release notes and lockfile committed
- Publish and post-publish smoke checks complete
