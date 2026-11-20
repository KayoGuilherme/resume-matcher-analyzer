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

## Resumes API

Import a resume (PDF or DOCX) and see how readable it is for an ATS. Single user, no
authentication.

```bash
curl -F "file=@resume.pdf" localhost:8000/resumes      # 201 new, 200 if the same bytes exist
curl localhost:8000/resumes                             # all resumes, newest first, no text
curl localhost:8000/resumes/<id>                        # one resume with its text
curl -X DELETE localhost:8000/resumes/<id>              # 204
```

A resume has `id`, `original_filename`, `file_type` (`pdf`/`docx`), `size_bytes`, `sha256`,
`page_count` (null when unknown, common for DOCX), `metadata` (parser, character, word, table and
image counts), `issues` and `created_at`; `text` is only in the single-resume responses.

Uploads are checked by their content, not their name or declared type. The same bytes (sha256)
return the existing resume. The original file is kept in `RESUME_STORAGE_DIR` under its hash
(not its name); the limit is `RESUME_MAX_UPLOAD_BYTES` (default 5 MB).

| Status | Code | When |
|---|---|---|
| 413 | `file_too_large` | over the size limit |
| 415 | `unsupported_file_type` | the content is not a PDF or a DOCX (e.g. a text file named `.pdf`) |
| 422 | `empty_file` | zero bytes |
| 422 | `unreadable_file` | corrupted or password-protected |
| 422 | `no_extractable_text` | no text layer, e.g. a scanned or image-only PDF (the message explains the ATS problem) |
| 404 | `resume_not_found` | unknown id |

Parsing-quality `issues` (each has `code`, `severity` and `message`, critical first):

| Code | Severity | Meaning |
|---|---|---|
| `image_only_pdf` | critical | only images, no text (such files are rejected, see above) |
| `multi_column` | warning | text in side-by-side columns |
| `tables` | warning | tables (ruled tables in PDF, any table in DOCX) |
| `header_footer_content` | warning | text in the header/footer area (top/bottom 7% of a PDF page) |
| `low_text_ratio` | warning | under 500 characters per page on average |
| `special_glyph_bullets` | warning | lines starting with icons/special symbols instead of `•`, `-`, `*` |
| `missing_experience_section`, `missing_education_section`, `missing_skills_section` | warning | no heading line for that section (English or Portuguese) |
| `too_many_pages` | info | more than 3 pages |

The text is extracted the way a simple ATS reads it: a two-column PDF is read line by line across
both columns. Known limits: borderless tables and text boxes are not detected; the column,
header/footer and density checks are heuristics tuned on generated documents; DOCX page counts
come from the document properties, which Word may not keep up to date.

Starlette stores an upload before the size check runs; requests whose `Content-Length` is far over
the limit are rejected early, but in production also set a request body limit in the reverse proxy.

## Repository settings (manual)

Workflows cannot apply these GitHub settings; configure them once under Settings:

- Protect the `main` branch.
- Require pull requests and disallow direct pushes to `main`.
- Require the status checks `lint`, `typecheck`, `test`, `integration` and `docker-build`
  (CI), plus the PR-rules checks `title` and `commits`.
- Allow squash merging only, using the pull request title as the commit message.

Renaming a job silently removes it from the required checks, so keep the names above.
