# ATS Resume Analyzer

Backend (Python 3.12, FastAPI, PostgreSQL + pgvector) that compares a resume against a job
position and reports what is missing to pass ATS/AI first-step screening.
This repo currently contains the project skeleton only.

## Run with Docker

```bash
cp .env.example .env          # placeholders only; edit if you like
docker compose up --build     # starts api (port 8000) and db (pgvector/pg16)
curl localhost:8000/health    # {"status":"ok","database":"ok"}
```

Apply the database migrations (enables the `vector` extension):

```bash
docker compose exec api alembic upgrade head
```

Configuration is read only from environment variables (see `.env.example`). Inside Docker
the database host is `db`; if you run tools on your host machine, use `localhost` in
`DATABASE_URL` and expose the db port yourself.

## Develop

Requires [uv](https://docs.astral.sh/uv/).

```bash
uv sync                                              # install deps
uv run pytest                                        # unit tests (no database needed)
uv run pytest --cov                                  # + branch coverage, fails under 80%
uv run pytest -m integration                         # integration tests (need DATABASE_URL, see below)
uv run ruff check . --fix && uv run ruff format .    # lint + format
uv run mypy src                                      # types (strict)
```

Integration tests (marked `integration`, excluded from the default run) need a migrated
PostgreSQL with pgvector, as in CI: start `pgvector/pgvector:pg16`, export `DATABASE_URL`,
then run `uv run alembic upgrade head`, `uv run alembic check` and
`uv run pytest -m integration`. The coverage threshold lives in `pyproject.toml`
(`[tool.coverage.report] fail_under`).

Run the API locally (needs a reachable Postgres and `DATABASE_URL` set):

```bash
uv run --env-file .env uvicorn app.main:app --reload
```

## Migrations

```bash
uv run alembic revision --autogenerate -m "describe the change"   # create
uv run alembic upgrade head                                        # apply
```

Never edit an applied migration; create a new one. Inside Docker, prefix with
`docker compose exec api`.

## Repository settings (manual)

Workflows cannot apply these GitHub settings; configure them once under Settings:

- Protect the `main` branch.
- Require pull requests and disallow direct pushes to `main`.
- Require the status checks `lint`, `typecheck`, `test`, `integration` and `docker-build`
  (CI), plus the PR-rules checks `title` and `commits`.
- Allow squash merging only, using the pull request title as the commit message.

Renaming a job silently removes it from the required checks, so keep the names above.
