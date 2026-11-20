# Tasks

## 1. Project setup

- [x] 1.1 Create `pyproject.toml` (Python 3.12, src layout, build backend, runtime deps and dev dependency group as in the proposal; ruff, mypy strict and pytest/asyncio config), run `uv sync`, and verify `uv.lock` is created and `uv run python -c "import app"` works once `src/app/__init__.py` exists
- [x] 1.2 Add `.gitignore` (venv, caches, `.env`, `__pycache__`) and `.env.example` (`DATABASE_URL`, `POSTGRES_USER/PASSWORD/DB`, `LOG_LEVEL`, `APP_ENV`; placeholders only) and verify `.env` is ignored and `.env.example` contains no real secrets

## 2. Core: configuration and errors

- [x] 2.1 Write tests for settings (loads from env; missing `DATABASE_URL` fails naming the field), then implement `src/app/core/config.py` with cached `get_settings()`; verify `uv run pytest tests/core/test_config.py` passes
- [x] 2.2 Write tests for `DomainError` handling (status/code/message mapped to JSON; unexpected exception → generic 500 without details), then implement `src/app/core/errors.py` with the base error, `register_error_handlers`; verify `uv run pytest tests/core/test_errors.py` passes
- [x] 2.3 Write tests for the JSON log formatter and `configure_logging` (valid JSON line, level respected, no message leakage of extra fields), then implement `src/app/core/logging.py`; verify `uv run pytest tests/core/test_logging.py` passes

## 3. Database access and health endpoint

- [x] 3.1 Implement `src/app/core/db.py` (lazy cached engine/sessionmaker from settings, `get_session` dependency with `pool_pre_ping`) and a unit test that importing the module creates no engine and `get_session` is a usable dependency; verify `uv run pytest tests/core/test_db.py` passes without a database
- [x] 3.2 Write `tests/health/test_router.py` using `httpx.AsyncClient` + `ASGITransport` with `get_session` overridden (DB ok → 200 `{"status":"ok","database":"ok"}`; DB raising a driver error containing a DSN → 503, body without the error text; slow DB → 503 via timeout), then implement `src/app/health/router.py`; verify the tests pass with no real DB
- [x] 3.3 Implement `src/app/main.py` (`create_app()` wiring logging, error handlers and the health router; `app = create_app()`) with a test that the app exposes `/health`; verify `uv run pytest` passes

## 4. Migrations

- [x] 4.1 Initialize async Alembic (`alembic.ini` without a URL, `alembic/env.py` reading the URL from `Settings`, `script.py.mako`, `versions/`) and verify `uv run alembic heads` runs without error
- [x] 4.2 Add first migration enabling pgvector (`upgrade`: `CREATE EXTENSION IF NOT EXISTS vector`; `downgrade`: `DROP EXTENSION IF EXISTS vector`) and add a unit test that the migration module exposes the expected revision and SQL; verify with `uv run pytest` (real-DB check happens in group 5)

## 5. Docker and docs

- [x] 5.1 Write the multi-stage `Dockerfile` (python:3.12-slim, uv builder with `--no-dev`, non-root final user, copies `alembic/` + `alembic.ini`) and `.dockerignore` (`.env`, `.venv`, `.git`, caches, `tests`); verify `docker build .` succeeds, `docker run --rm <image> id -u` is non-zero and `pytest`/`ruff`/`mypy` are not present in the image
- [x] 5.2 Write `docker-compose.yml` (`db` pgvector/pgvector:pg16 with `pg_isready` healthcheck and named volume; `api` with `env_file: .env`, `depends_on` service_healthy, port 8000); verify `docker compose config` validates
- [x] 5.3 Write a short `README.md` (run with Docker, host `DATABASE_URL` vs. container host note, tests/lint/types commands, create and apply a migration); verify each documented command runs as written
- [x] 5.4 End-to-end acceptance check: copy `.env.example` to `.env`, run `docker compose up --build`, verify `curl localhost:8000/health` returns 200 with database ok, `docker compose exec api alembic upgrade head` succeeds, `docker compose exec db psql -U <user> -d <db> -c '\dx'` lists `vector`, stopping the db makes `/health` return 503, and the data volume survives `docker compose down` + `up`
- [x] 5.5 Final quality gate: verify `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .` and `uv run mypy src` all pass, and `git status`/ignore rules show no `.env` or secrets would be committed
