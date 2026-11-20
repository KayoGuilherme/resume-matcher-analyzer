# Tasks

Write each test first or together with the code. Every group ends green on `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy src` and `uv run pytest` (default run: no database).

## 1. Name normalization

- [x] 1.1 Write `tests/core/test_normalization.py` and implement `src/app/core/normalization.py` (`normalize_stack_name`, `normalize_language_name`; trim, collapse whitespace, lowercase, accent-insensitive alias lookup, two read-only alias maps with the aliases of the `name-normalization` spec, unknown names only cleaned); verify the tests cover every scenario of the spec (case and spacing, idempotence, stack aliases, language aliases `pt`/`Português`/`portugues`, `pt` unchanged as a stack, unknown name) and pass

## 2. Validation error envelope

- [x] 2.1 Write tests in `tests/core/test_errors.py` and add a `RequestValidationError` handler to `src/app/core/errors.py` (registered in `register_error_handlers`) returning 422 with `{"error": {"code": "validation_error", "message": "<field>: <reason>; ..."}}` built only from each error's `loc` (without the leading `body`) and `msg`; verify tests for one invalid field, several invalid fields, and a recognizable secret string in an invalid value that must not appear in the response body

## 3. Profile schemas

- [x] 3.1 Write `tests/profile/test_schemas.py` and create `src/app/profile/__init__.py` and `schemas.py` (`ProfileIn`, `StackIn`, `LanguageIn`, `ProfileOut`, `StackOut`, `LanguageOut`; `extra="forbid"`, whitespace stripping, enums as `Literal`, years `0..60` and finite, length and list-size limits, `last_year_used` from 1970 to the current year); verify tests for a valid profile, each enum, negative years, years above 60, empty and too long text, an unknown field, optional `last_year_used` (absent, future year, 1969), empty lists, and list-size limits, all passing

## 4. Model and migration

- [x] 4.1 Create `src/app/profile/models.py` (`CandidateProfile(Base)`: `id` smallint primary key with `CHECK (id = 1)`, `target_role`, `seniority`, `total_years_coding`, JSONB `stacks`, `languages`, `notable_facts`) and import it in `alembic/env.py`; verify `uv run mypy src` passes and the model appears in `Base.metadata.tables` (small unit test)
- [x] 4.2 Generate `alembic/versions/*-0002_*.py` with `uv run alembic revision --autogenerate -m "create candidate profile" --rev-id 0002` against a throwaway `pgvector/pgvector:pg16`, review it by hand (columns, `CHECK`, `downgrade` drops the table, `down_revision = "0001"`), and add unit tests in `tests/alembic/test_migrations.py` for the revision chain and for `upgrade`/`downgrade` (calls to `op` monkeypatched); verify `alembic upgrade head`, `alembic check` ("No new upgrade operations detected") and `alembic downgrade 0001` followed by `upgrade head` all succeed on that database, and that inserting a row with `id = 2` is rejected by the database
- [x] 4.3 Verify the model is really watched by `alembic check`: temporarily add a column to the model without a migration, confirm `alembic check` fails, then revert it

## 5. Repository

- [x] 5.1 Write `tests/profile/test_repository.py` (fake `AsyncSession`) and implement `src/app/profile/repository.py` (`ProfileRepository(session)`: `get() -> ProfileOut | None`, `save(ProfileOut) -> None` as `INSERT ... ON CONFLICT (id) DO UPDATE` with `id = 1`, then `commit`; maps between the row and `ProfileOut`, no business rules); verify tests for: no row returns `None`, a stored row maps back to an equal `ProfileOut`, `save` issues an upsert on id 1 and commits

## 6. Service

- [x] 6.1 Write `tests/profile/test_service.py` (fake repository) and implement `src/app/profile/service.py` (`ProfileService.save` normalizes stack and language names keeping `original_name`, collects all violations — duplicate normalized names within stacks and within languages, stack years above total years — and raises `InvalidProfileError` (422, `invalid_profile`, positions only, no profile text) before touching the repository; `get` raises `ProfileNotFoundError` (404, `profile_not_found`)); verify tests for normalization with `original_name`, `Postgres`+`PostgreSQL` duplicate, a stack with years equal to and above the total, a stack and a language with the same normalized name (accepted), several violations reported in one error, nothing saved on error, `get` with and without a profile, and that no profile text is logged (`caplog`)

## 7. Router, wiring and docs

- [x] 7.1 Write `tests/profile/test_router.py` (service overridden through `dependency_overrides`) and implement `src/app/profile/router.py` (`PUT /profile`, `GET /profile`, `response_model=ProfileOut`, `get_profile_service` dependency) and include it in `src/app/main.py`; verify tests for PUT 200 with the normalized body, GET 200, GET 404 error body, PUT 422 for schema violations in the `validation_error` envelope, and PUT 422 for service violations in the `invalid_profile` envelope
- [x] 7.2 Document `PUT /profile` and `GET /profile` in `README.md` (fields, rules, normalization, error format, that a `GET` body is not accepted by `PUT` because of `original_name`) with one runnable `curl` example; verify the example runs against `docker compose up --build` (after `alembic upgrade head`) and returns the documented response

## 8. Integration and final gate

- [x] 8.1 Write `tests/profile/test_router_integration.py` (marked `integration`, real app and database like `tests/health/test_router_integration.py`, engine disposed, profile row removed before and after each test): PUT then GET returns an equal normalized body, a second PUT replaces the first, a rejected PUT leaves the stored profile unchanged, GET returns 404 when no row exists; verify with `uv run pytest -m integration` against a throwaway `pgvector/pgvector:pg16` after `alembic upgrade head`
- [x] 8.2 Run the full gate: `uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run pytest --cov` (coverage >= 80%), plus `alembic upgrade head`, `alembic check` and `pytest -m integration` on the throwaway database, and `docker build .`; verify all pass and that no test or log output contains profile text
