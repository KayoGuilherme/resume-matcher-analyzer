# Proposal

## Why

The candidate profile is the source of truth about the candidate. Later changes use it to find things the candidate knows but the resume does not show, so it must be stored in a clean, comparable form. This is a single-user app for now: one profile, no authentication.

## What Changes

- Add the `profile` feature (`src/app/profile/`: router, schemas, models, repository, service) with two endpoints: `PUT /profile` (create or replace the one profile) and `GET /profile`.
- Profile fields: target role, self-declared seniority (`junior`/`mid`/`senior`), total years coding, stacks, spoken languages and a free-text list `notable_facts`. A stack has a name, years of experience, a level (`learning`/`working`/`proficient`/`expert`) and an optional last year used. A language has a name and a level (`A1`..`C2` or `native`).
- Business rules: years are >= 0; a stack's years cannot exceed total years coding; stack and language names are normalized and must be unique after normalization; the name as typed is kept next to the normalized one.
- Add `src/app/core/normalization.py`: a small, reusable, case-insensitive alias map (e.g. `springboot` -> `spring boot`, `postgres` -> `postgresql`, `js` -> `javascript`, `pt`/`português` -> `portuguese`). Later changes reuse it for resumes and jobs.
- Invalid input returns 422 with clear, field-level messages. Request-validation errors (malformed or out-of-range values) are rendered in the same error envelope as domain errors and never echo the submitted values.
- Add a table for the single profile and the Alembic migration `0002` that creates it. The model is imported in `alembic/env.py` so `alembic check` sees it.
- Tests: unit tests for normalization, schemas, service rules and the router (repository and DB mocked), a migration test, and one `integration` test for PUT then GET against the real database.
- No new dependencies.

## Capabilities

### New Capabilities
- `candidate-profile`: storing and reading the single candidate profile through `PUT /profile` and `GET /profile`, its fields, validation rules and normalization behavior.
- `name-normalization`: the reusable canonical-name normalization for stack/technology names and spoken-language names (case-insensitive, aliases, original text preserved by callers).

### Modified Capabilities
- `error-handling`: request-validation failures are reported as HTTP 422 in the same JSON error envelope as domain errors, with field-level messages and without the submitted values.

## Impact

- New code: `src/app/profile/{__init__,router,schemas,models,repository,service}.py`, `src/app/core/normalization.py`, `alembic/versions/*-0002_*.py`, and matching tests under `tests/profile/`, `tests/core/` and `tests/alembic/`.
- Modified: `src/app/main.py` (include the profile router), `src/app/core/errors.py` (validation error handler), `alembic/env.py` (import the profile model), `README.md` (document the endpoints).
- New public API: `PUT /profile`, `GET /profile`. Existing endpoints are unchanged.
- Builds on `Base` from `src/app/core/db.py` and the `integration` test setup introduced by `add-ci-cd-pipeline` (both already in the working tree; that change still has task 6.2 open).
- The profile contains personal data: it must never be logged and never appear in error responses.
- Out of scope: authentication, multiple users, resume or job features, any AI code, `target_role` normalization.
