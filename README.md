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

The profile integration tests empty the `candidate_profile` table before and after each test,
so run them only against a throwaway database, never one that holds your real profile.

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

## Candidate profile API

One profile (single user, no authentication). `PUT /profile` creates or replaces it, `GET /profile`
returns it (404 if none was saved).

```bash
curl -X PUT localhost:8000/profile -H 'content-type: application/json' -d '{
  "target_role": "Backend Developer",
  "seniority": "mid",
  "total_years_coding": 5,
  "stacks": [{"name": "Springboot", "years": 3, "level": "working", "last_year_used": 2024}],
  "languages": [{"name": "pt", "level": "native"}],
  "notable_facts": ["Built a payments API"]
}'
curl localhost:8000/profile
```

Fields: `seniority` is `junior|mid|senior`; stack `level` is `learning|working|proficient|expert`;
language `level` is `A1`..`C2` or `native`; years are numbers from 0 to 60 and a stack's years
cannot exceed `total_years_coding`; `last_year_used` is optional (1970 up to the current year).
Unknown fields are rejected.

Stack and language names are normalized (case-insensitive, aliases such as `springboot` ->
`spring boot`, `postgres` -> `postgresql`, `js` -> `javascript`, `pt` -> `portuguese`; see
`src/app/core/normalization.py`). Each item in the response has the normalized `name` and the text
you typed in `original_name`; duplicates after normalization are rejected. Because of
`original_name`, a `GET` response cannot be sent back to `PUT` unchanged.

Invalid input returns 422 with `{"error": {"code": ..., "message": ...}}`: `validation_error` for
malformed values and `invalid_profile` for the rules between fields (stack years, duplicates).
Messages name the field or list position (`stacks[1]`) and never repeat what you sent.

## Repository settings (manual)

Workflows cannot apply these GitHub settings; configure them once under Settings:

- Protect the `main` branch.
- Require pull requests and disallow direct pushes to `main`.
- Require the status checks `lint`, `typecheck`, `test`, `integration` and `docker-build`
  (CI), plus the PR-rules checks `title` and `commits`.
- Allow squash merging only, using the pull request title as the commit message.

Renaming a job silently removes it from the required checks, so keep the names above.
