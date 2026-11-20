# Design

## Context

See proposal.md for motivation and the specs for behavior. Observed current state:

- `src/app/` has `core/` (`config`, `db`, `errors`, `logging`) and `health/`. There are no models yet; `core/db.py` already has `Base(DeclarativeBase)` and the cached lazy engine/sessionmaker, and `get_session` yields one `AsyncSession` per request.
- `core/errors.py` has `DomainError` (with `status_code`, `code`) and one central handler producing `{"error": {"code", "message"}}`. There is no handler for FastAPI's `RequestValidationError`, whose default 422 body is `{"detail": [...]}` and includes the submitted `input`.
- `alembic/env.py` uses `target_metadata = Base.metadata`, with a comment that every model module must be imported there. Only migration `0001` (pgvector) exists, with file names like `2026_11_20_1710-0001_enable_pgvector.py`.
- CI (from `add-ci-cd-pipeline`) runs `alembic upgrade head`, `alembic check` (models vs migrations) and `pytest -m integration` against a real pgvector Postgres; unit tests must not need a database and total branch coverage must stay >= 80%.
- Project rules that shape this design: router -> service -> repository; Pydantic v2 and SQLAlchemy 2.0 async; domain exceptions mapped only in `core/errors.py`; no resume/personal data in logs; mypy strict.

## Goals / Non-Goals

**Goals:**
- One validated, normalized profile persisted in PostgreSQL, behind `PUT /profile` and `GET /profile`.
- A pure, reusable normalization module that later changes (resumes, jobs) can import unchanged.
- One 422 format for every kind of invalid input, without echoing submitted values.

**Non-Goals:**
- Authentication, multiple profiles, partial updates (`PATCH`), history or versioning of the profile.
- Normalizing `target_role` or `notable_facts`, fuzzy matching, or a large alias dictionary.
- Embeddings, AI code, or any use of the profile by the analysis (later changes).

## Decisions

**1. One row in a table with a fixed key; list fields stored as JSONB.**
Table `candidate_profile`: `id` (smallint primary key, `CHECK (id = 1)`), `target_role` (text), `seniority` (text), `total_years_coding` (double precision), `stacks`, `languages`, `notable_facts` (JSONB, not null). `PUT` is an atomic upsert (`INSERT ... ON CONFLICT (id) DO UPDATE`), so there is no read-then-write race and "create or replace" is a single statement. The `CHECK` makes "exactly one profile" a database guarantee, and keeps the door open to a real `user_id` key when multi-user arrives (a new migration then). JSONB fits because `PUT` always replaces the whole document, items have no identity of their own, and nothing queries inside them yet. Alternatives: child tables `profile_stack` / `profile_language` (more models, joins and migrations for no current query need; can be introduced later by a migration that unpacks the JSON); a single JSONB column for everything (loses typed scalar columns and constraints). Seniority and levels are plain text validated by Pydantic, not PostgreSQL enums, because enum changes need awkward migrations.

**2. Validation is split in two layers, both ending in HTTP 422.**
- Schemas (`profile/schemas.py`, Pydantic v2, `extra="forbid"`, `str_strip_whitespace=True`): types, required fields, enums (`Literal`), ranges (`0..60`), lengths and list sizes, `last_year_used` between 1970 and the current year (field validator using the clock; tests build the year relative to now). Failures are `RequestValidationError`.
- Service (`profile/service.py`): the rules that depend on normalization or on comparing fields — duplicate normalized names (within stacks, within languages) and stack years > total years. It collects all violations and raises one `InvalidProfileError(DomainError)` with `status_code = 422`, `code = "invalid_profile"`, and a message listing each violation by field path or list position (never quoting profile text). These rules are business rules, so they stay out of the schema.
Because a schema failure stops the request before the service runs, comparison rules are reported once all field values are valid; the spec states this explicitly. Alternative: put every rule in `model_validator`s so that the framework reports everything. Rejected: normalization (business logic) would then run inside the schema, against the project's router/schema/service split.

**3. 422 envelope for request validation (modifies `core/errors.py`).**
Register a handler for `RequestValidationError` returning 422 with `{"error": {"code": "validation_error", "message": "<field>: <reason>; ..."}}`. The message is built only from each error's `loc` (field path, dropping the leading `body`, e.g. `stacks[0].years`) and `msg`; `input` and `ctx` are never read. Pydantic `msg` texts do not contain the submitted value, but this is covered by a test with a recognizable secret string in an invalid field. Custom validator messages in this feature never interpolate input. Alternative: leave FastAPI's default. Rejected: two 422 shapes in one API, and the default echoes `input` (the profile is personal data).

**4. Normalization in `core/normalization.py`: pure functions plus two alias maps.**
`normalize_stack_name(text)` and `normalize_language_name(text)`, built on one helper: clean (trim, collapse whitespace, lowercase), then look up the cleaned text with accents removed (Unicode NFKD, combining marks dropped) in the matching alias map; return the canonical name on a hit, otherwise the cleaned text (accents kept). Maps are module constants (read-only mappings) with already-clean keys. Two maps because aliases are only meaningful per kind (`pt` is a language, not a stack). Initial content: stacks `springboot`, `postgres`, `js`; languages `pt`, `português`, `en`, `inglês` (the last two are an assumption by symmetry with `pt`; trivial to drop). Keeping it small and in code was requested; growing it later is a one-line change. The module has no I/O and no dependency on the profile, so resumes and jobs can reuse it. Callers keep the original text themselves (the function returns only the normalized text).

**5. Layers and wiring.**
- `schemas.py`: `ProfileIn` (with `StackIn`, `LanguageIn`) for requests; `ProfileOut` (with `StackOut` having `name` + `original_name`, `LanguageOut` likewise) for responses and for what is stored. Input has no `original_name`: the original is the `name` the client typed. Consequence: a `GET` body is not directly accepted by `PUT` (`extra="forbid"`); accepted, since `forbid` catches typos of optional fields such as `last_year_used`.
- `models.py`: `CandidateProfile(Base)` mapped as in decision 1.
- `repository.py`: `ProfileRepository(session)` with `get() -> ProfileOut | None` and `save(profile: ProfileOut) -> None` (upsert, then `commit`). It is the only place that touches the table and maps between the row and `ProfileOut`; it holds no business rules.
- `service.py`: `ProfileService(repository)` with `save(ProfileIn) -> ProfileOut` (normalize, check rules, persist, return) and `get() -> ProfileOut` (raises `ProfileNotFoundError`, 404, code `profile_not_found`). Both exceptions live here and subclass `DomainError`; no new file is added to the feature folder.
- `router.py`: `PUT /profile` and `GET /profile` (`response_model=ProfileOut`, 200), and the `get_profile_service` dependency (`Depends(get_session)` -> repository -> service). `main.py` only includes the router.
- Logging: no profile content is logged. The service may log the event and counts only.

**6. Migration `0002` and Alembic wiring.**
Generate with `alembic revision --autogenerate --rev-id 0002`, then review by hand (table, `CHECK`, JSONB columns, `downgrade` drops the table). Import `app.profile.models` in `alembic/env.py` (the documented follow-up of `add-candidate-profile`'s predecessor) so `alembic check` in CI sees the model and fails on drift. The migration is a new file; `0001` is untouched.

**7. Testing strategy (unit tests do not touch a database).**
- `tests/core/test_normalization.py`: aliases, accents, case, whitespace, idempotence, per-kind maps.
- `tests/core/test_errors.py`: the validation handler (envelope, multiple fields, no echo).
- `tests/profile/test_schemas.py`, `test_service.py` (fake repository), `test_repository.py` (fake session capturing the statement and returning a row), `test_router.py` (service overridden via `dependency_overrides`), and `tests/alembic/test_migrations.py` additions (revision chain, create/drop).
- `tests/profile/test_router_integration.py` (marked `integration`): PUT then GET against the real database, replace, and a rejected PUT leaving the old profile. It must clean the table and dispose of its engine like the existing health integration test.

## Risks / Trade-offs

- [JSONB lists cannot be queried relationally and have no per-item constraints] -> acceptable now (whole-document replace, no queries); a later migration can normalize into tables if the analysis needs it.
- [Small alias map misses common spellings (`node.js`, `ts`)] -> deliberate; extend the map when real data shows gaps; names without alias are still cleaned and de-duplicated by case.
- [A client that sends back a `GET` body to `PUT` gets 422 because of `original_name`] -> documented in the README; `forbid` is kept to catch typos.
- [`last_year_used` bound depends on the current date] -> tests compute years from the clock; no frozen-time dependency is added.
- [Model not imported by `env.py` makes `alembic check` blind to it] -> the import is a task with a verification (a temporary column change must fail `alembic check`).
- [Validation errors could leak personal data] -> handler built only from `loc`/`msg`, covered by a leak test; service messages identify items by list position (`stacks[1]`) and never quote profile text; nothing is logged.
- [Single-profile `CHECK (id = 1)` blocks multi-user] -> intentional; multi-user is a later change with its own migration.
- [Float years allow values like 2.5] -> intended (half years); bounded to 60 and finite.
