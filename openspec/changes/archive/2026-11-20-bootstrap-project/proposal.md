# Proposal

## Why

This is the first change of the ATS Resume Analyzer. There is no code yet. We need a working, empty backend skeleton (Python + FastAPI + PostgreSQL with pgvector, running in Docker) that follows the rules in `CLAUDE.md`, so every later feature starts from a solid base with tests, lint and types already working.

## What Changes

- Add a Python 3.12 project managed with `uv` (`pyproject.toml`, `src/app` layout), with runtime deps (fastapi, uvicorn[standard], pydantic-settings, sqlalchemy[asyncio], asyncpg, alembic) and dev deps (pytest, pytest-asyncio, httpx, ruff, mypy). Ruff, mypy (strict) and pytest are configured in `pyproject.toml`.
- Add the minimal folder structure from `CLAUDE.md`: `src/app/main.py` (app factory + router inclusion only), `src/app/core/` (`config.py`, `db.py`, `logging.py`, `errors.py`), `src/app/health/` (`router.py`), and `tests/` mirroring `src/app`. No resumes/jobs/profile/analyses/ai modules yet.
- Add `GET /health`: 200 with app status and database connectivity; 503 when the database is unreachable.
- Configure Alembic for async SQLAlchemy and add a first migration that runs `CREATE EXTENSION IF NOT EXISTS vector`.
- Add Docker packaging: multi-stage `Dockerfile` (python:3.12-slim, uv, non-root user, no dev deps in final image), `docker-compose.yml` (`api` + `db` using `pgvector/pgvector:pg16`, db healthcheck, named volume, api waits for healthy db, env from `.env`, port 8000), `.dockerignore`, `.gitignore`, `.env.example`.
- Add a short `README.md` (run with Docker, run tests/lint/types, create and apply a migration).

Out of scope (separate changes): CI/CD, any AI code (LLM, embeddings, parsing), resume/job/profile features, authentication, deployment.

## Capabilities

### New Capabilities
- `app-configuration`: all configuration comes only from environment variables via pydantic-settings; `.env.example` documents them without real secrets.
- `error-handling`: base domain exception and a single place that maps domain errors to HTTP responses.
- `health-check`: `GET /health` reports app status and database connectivity (200 / 503).
- `database-migrations`: Alembic with async SQLAlchemy; first migration enables the pgvector extension.
- `container-runtime`: Docker image and Docker Compose setup to run the API and its pgvector database locally.

### Modified Capabilities
<!-- None: the project has no existing specs. -->

## Impact

- New files only (greenfield): `pyproject.toml`, `uv.lock`, `src/app/**`, `tests/**`, `alembic.ini`, `alembic/**`, `Dockerfile`, `docker-compose.yml`, `.dockerignore`, `.gitignore`, `.env.example`, `README.md`.
- New dependencies are exactly those listed above (explicitly requested; nothing else is added).
- Sets the conventions (DI via `Depends`, async DB access, structured logging, typed domain errors) that all later changes build on.
