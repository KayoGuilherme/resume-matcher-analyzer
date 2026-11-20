# Design

## Context

Greenfield repo: only `.claude/` and `openspec/` exist. `CLAUDE.md` fixes the stack (Python 3.12, FastAPI, async SQLAlchemy 2.0 + asyncpg, Postgres + pgvector, `uv`) and the folder layout, and forbids global state / import-time singletons, inline prompts, and extra dependencies. This change only builds the skeleton; see proposal.md for scope and the specs for observable behavior.

Note: `CLAUDE.md` lists the run command as `uvicorn app.main:app` and mypy as `mypy src`, so the code lives in `src/app` and the package must be installed (editable) by `uv`.

## Goals / Non-Goals

**Goals:**
- A skeleton where `pytest`, `ruff check`, `ruff format --check` and `mypy src` (strict) pass from day one.
- Conventions later features copy: app factory, DI for settings/DB session, typed domain errors, structured logging.
- Reproducible local stack via Docker Compose.

**Non-Goals:**
- Any ORM models or tables (the only migration enables the extension).
- Integration tests against a real Postgres, CI, readiness vs. liveness split, metrics.
- Request-id middleware, auth, CORS.

## Decisions

**1. App factory, no import-time singletons.** `main.py` exposes `create_app()` (builds `FastAPI`, registers the error handler, includes routers) and `app = create_app()` for uvicorn (`uvicorn app.main:app` per CLAUDE.md). The factory itself holds no logic beyond wiring. Settings, engine and session factory are *not* created at import: `get_settings()` is an `lru_cache`d function used via `Depends`, and `db.py` creates the engine lazily from settings (cached function, also behind `Depends`). Alternative: module-level `engine = create_async_engine(...)` — rejected, it violates the "no singletons at import time" rule and breaks tests when env is missing.

**2. Settings.** `core/config.py`: `Settings(BaseSettings)` with `database_url` (required, `postgresql+asyncpg://...`), `log_level` (default `INFO`), `app_env` (default `local`). Reads environment only (no `env_file` in code; Compose injects `.env`, and locally users export vars or use `uv run --env-file .env`). A missing `database_url` raises a pydantic `ValidationError` naming the field. Alternative: `env_file=".env"` in `SettingsConfigDict` — rejected to keep "config only from environment" literal and avoid reading a file inside the image.

**3. DB access.** `core/db.py`: `get_engine(settings)` / `get_sessionmaker(...)` cached by settings; `get_session()` async generator dependency yielding an `AsyncSession` (`expire_on_commit=False`). `pool_pre_ping=True`. Declarative `Base` is **not** added yet (no models; Alembic `target_metadata = None` for now — later changes add `Base` with their first model).

**4. Health endpoint.** `health/router.py` only (as requested; no service/repository yet since there is no business rule). The route depends on `get_session` and runs `SELECT 1` with a short timeout (`asyncio.wait_for`, 2 s). Response model is a small Pydantic model defined in the router module:
- 200: `{"status": "ok", "database": "ok"}`
- 503: `{"status": "degraded", "database": "unavailable"}`
Any exception from the check is caught (`except Exception`, never bare) and logged with exception *type only*, never the message (drivers can echo DSNs). Caveat: this puts a tiny DB query in a router, which bends "routers never touch the DB"; accepted for the health probe only, since a service/repository layer for `SELECT 1` is ceremony. If this is not acceptable, move it to `health/service.py` + `repository.py` — a cheap change. Unit tests override `get_session` with a fake (OK / raising) so no DB is needed.

**5. Errors.** `core/errors.py`: `class DomainError(Exception)` with class attributes `status_code = 400`, `code = "domain_error"` and a `message`. `register_error_handlers(app)` adds one handler for `DomainError` returning `{"error": {"code": ..., "message": ...}}`, and a catch-all handler for `Exception` returning a generic 500 (`code = "internal_error"`) while logging only the exception type. Specific domain errors are subclasses added by later features. Open-ended `HTTPException`/validation (422) handling stays FastAPI's default.

**6. Logging.** `core/logging.py`: `configure_logging(level)` using stdlib `logging` with a JSON formatter written in ~20 lines (no new dependency), writing to stdout. Called from the app factory/lifespan using settings. Convention documented in a docstring: never log resume content or personal data.

**7. Alembic (async).** `alembic init -t async` layout at repo root (`alembic.ini`, `alembic/env.py`, `alembic/versions/`). `env.py` takes the URL from `Settings` (env var), not from `alembic.ini`, so there is one source of config; `alembic.ini` has no URL. Migration `0001_enable_pgvector` runs `CREATE EXTENSION IF NOT EXISTS vector` in `upgrade()`; `downgrade()` runs `DROP EXTENSION IF EXISTS vector`. Filename template set to date/rev-prefixed names so ordering is obvious. Migrations are *not* run automatically on container start (acceptance criteria run them explicitly via `docker compose exec api alembic upgrade head`).

**8. Packaging with uv.** `pyproject.toml` with a build backend (hatchling) and `[tool.hatch.build.targets.wheel] packages = ["src/app"]` so `app` is importable after `uv sync`; dev deps in `[dependency-groups] dev`. Tool config: ruff (`line-length = 100`, rules `E,F,I,B,UP,ASYNC,S` with `S101` ignored under `tests/`), mypy `strict = true` with the pydantic plugin not needed, pytest `asyncio_mode = "auto"`, `testpaths = ["tests"]`. `uv.lock` is committed. hatchling is a build-system requirement, not a runtime dependency; flagged here since CLAUDE.md says to ask before adding dependencies. Alternative: `uv_build` backend — also acceptable; I'm choosing hatchling as the most common. Either is a build-only choice and can be swapped on request.

**9. Docker.** Multi-stage `Dockerfile`: *builder* `python:3.12-slim` + uv (copied from `ghcr.io/astral-sh/uv`, pinned tag) runs `uv sync --frozen --no-dev --no-editable` into `/app/.venv` (deps layer first via `--no-install-project` for caching, then project); *final* `python:3.12-slim` copies only `.venv`, `alembic/`, `alembic.ini`, creates a non-root user, sets `PATH` to the venv, `CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]`. Because `alembic.ini` and `alembic/` are copied, `docker compose exec api alembic upgrade head` works. No dev deps in the final image, no `uv` binary in it. A container `HEALTHCHECK` is not added (Compose handles db health; keeps the image free of curl).

**10. Compose.** `db`: `pgvector/pgvector:pg16`, env from `.env` (`POSTGRES_USER/PASSWORD/DB`), `pg_isready` healthcheck, named volume `pgdata`. `api`: `build: .`, `env_file: .env`, `depends_on: db: condition: service_healthy`, `ports: "8000:8000"`. `DATABASE_URL` in `.env.example` points at host `db`; running tools on the host (tests don't need it) would use `localhost` — noted in README. The `db` port is not published by default, to avoid clashing with a local Postgres.

**11. Tests.** `tests/` mirrors `src/app`: `tests/core/test_config.py`, `test_errors.py`, `test_logging.py`, `tests/health/test_router.py`, plus `tests/conftest.py` providing an `httpx.AsyncClient` over `ASGITransport` with dependency overrides. No real DB, network or LLM. The pgvector migration and the Docker stack are verified manually per the acceptance criteria (documented in tasks), not in unit tests.

## Risks / Trade-offs

- [Health route queries the DB directly] → Accepted for a trivial probe; easy to move behind a service/repository (Decision 4).
- [`app = create_app()` at import creates the app object] → It builds no engine/settings eagerly (lazy via `Depends`), so import stays side-effect free apart from route registration.
- [`DATABASE_URL` host differs inside Docker (`db`) vs. host (`localhost`)] → README documents it; `.env.example` defaults to the Docker case.
- [Hand-rolled JSON log formatter] → Small and tested; avoids a new dependency (structlog) which would need approval.
- [Image tag drift for `pgvector/pgvector:pg16`, `uv`] → Pin uv tag; db image follows the requested `pg16`.
- [`CREATE EXTENSION` needs privileges] → The official image's `POSTGRES_USER` is superuser, so it works locally; managed Postgres in deployment is a later concern.

## Migration Plan

Greenfield; nothing to migrate. Verification order for apply: unit tests/lint/types → `docker compose up --build` → `curl /health` → `docker compose exec api alembic upgrade head` → `\dx` shows `vector`. Rollback = delete the new files / `docker compose down -v`.
