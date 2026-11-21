# ATS Resume Analyzer

Backend (Python 3.12, FastAPI, PostgreSQL + pgvector) that compares a resume against a job
position and reports what is missing to pass ATS/AI first-step screening.
Stored resumes are parsed, extracted by an LLM into structured data and embedded for search.

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

## AI providers

The LLM (structured extraction) and the embeddings (vectors for search) are configured
independently in `.env`; switching provider is a change to those variables only, never to code.
Business code only knows the `LLMClient` and `EmbeddingClient` protocols; `ai/llm/` and
`ai/embeddings/` are the only places that call a provider.

| | `LLM_PROVIDER` | `EMBEDDING_PROVIDER` |
|---|---|---|
| Anthropic | `anthropic` | none: Anthropic has no embeddings model |
| OpenAI | `openai` | `openai` |
| Ollama, LM Studio, vLLM, any OpenAI-compatible server | `openai_compatible` (+ `LLM_BASE_URL`) | `openai_compatible` (+ `EMBEDDING_BASE_URL`) |
| Model inside the API process | none | `local` (optional dependency group, see below) |

`.env.example` has ready-to-copy blocks for Anthropic, OpenAI and a local Ollama. Without
`LLM_PROVIDER` the API runs normally and only `POST /resumes/{id}/process` answers
`503 ai_not_configured` (the message names the missing setting).

**Privacy:** with a hosted provider (Anthropic, OpenAI) the text of your resume is sent to that
company. A local server (Ollama, ...) keeps everything on your machine.

Behavior shared by all providers (the adapters stay thin): the model's answer is always validated
against a Pydantic schema, with one repair attempt before `llm_invalid_output`; the provider's
native structured output (tool use / JSON schema) is used when it works and the call falls back to
JSON-in-the-prompt when it does not (typical for small local models); `LLM_TEMPERATURE` (default
`0`) is only sent while the model accepts it (set it empty to never send one); rate limits and
server errors are retried 3 times with backoff; authentication errors and timeouts are not.

### Run with a local model (Ollama)

```bash
ollama pull bge-m3            # multilingual embeddings (Portuguese + English), 1024 dimensions
ollama pull <a-chat-model>    # any model that follows instructions well; bigger is better
OLLAMA_HOST=0.0.0.0 ollama serve
```

Then use the Ollama block of `.env.example`: `LLM_PROVIDER=openai_compatible`,
`LLM_BASE_URL=http://host.docker.internal:11434/v1`, `LLM_MODEL=<model name>` and the same base URL
for `EMBEDDING_*`.

How the container reaches a server on your machine: inside the container `localhost` is the
container itself, so use `host.docker.internal`. Docker Desktop defines that name; on Linux the
`docker-compose.yml` adds it (`extra_hosts: host.docker.internal:host-gateway`). The server must
listen on an address the container can reach: Ollama binds to `127.0.0.1` by default, which the
Docker bridge cannot reach, hence `OLLAMA_HOST=0.0.0.0` (mind your firewall: anyone on your network
can then use it). LM Studio: enable "Serve on Local Network"; vLLM: `--host 0.0.0.0`. Running the
API on the host instead of Docker, use `http://localhost:11434/v1`.

Small local models may return weaker structured output. That never becomes bad data: invalid
answers are repaired once, bullets that are not in the resume are dropped (see `warnings` in the
extraction), and a model that cannot produce valid output ends as `llm_invalid_output`.

### Local embeddings without a server (optional)

`EMBEDDING_PROVIDER=local` runs a sentence-transformers model inside the API process (for example
`EMBEDDING_MODEL=BAAI/bge-m3`, `EMBEDDING_DIMENSION=1024`). It needs a large optional dependency
group (torch) that is not in the default install or the default image:

```bash
uv sync --extra local-embeddings
docker build --build-arg EXTRAS="--extra local-embeddings" -t ats-api .
```

On Linux `torch` resolves to a CUDA build (several GB) unless you point uv at the CPU index. The
`docker-compose.yml` builds the default image; add the build argument under `api.build.args` to
use the opt-in one.

### Choosing the embedding model

| Option | Dim. | Notes |
|---|---|---|
| `bge-m3` via Ollama (**default**) | 1024 | best free multilingual quality, no query/passage prefixes, local, small image |
| `bge-m3` / `multilingual-e5-base` with `local` | 1024 / 768 | no server to run, but heavy dependency group |
| `multilingual-e5-small` with `local` | 384 | lowest CPU/RAM; E5 models expect `query:` / `passage:` prefixes, which this project does not add |
| OpenAI `text-embedding-3-small` | 1536 (cut to `EMBEDDING_DIMENSION` with `dimensions`) | easy hosted option, text leaves your machine |

`EMBEDDING_DIMENSION` is the size of the database column (1 to 2000, the limit of pgvector's HNSW
index). It is applied by migration `0004` when you run `alembic upgrade head`, so set it before the
first migration. At startup the API refuses to start if it differs from the column, naming both
sizes.

### Changing the embedding model

Vectors of different models are not comparable, even with the same dimension. Resume chunks and
job requirements both store the model that made them, so you can see what is stale:

```sql
SELECT 'resume_chunk' AS table_name, embedding_model, count(*) FROM resume_chunk GROUP BY 2
UNION ALL
SELECT 'job_requirements', embedding_model, count(*) FROM job_requirements GROUP BY 2;
```

- **Same dimension** (for example `bge-m3` to `multilingual-e5-base` with a 1024-wide setting): change
  `EMBEDDING_PROVIDER` / `EMBEDDING_MODEL`, restart, then `POST /resumes/{id}/process` for every
  resume and `POST /jobs/{id}/process` for every job (this re-runs the extraction too).
- **Different dimension**: write a new migration (never edit `0004` or `0005`) that, for **both**
  `resume_chunk` and `job_requirements`, drops the index (`ix_resume_chunk_embedding`,
  `ix_job_requirements_embedding`), deletes the rows (they are derived data), runs
  `ALTER TABLE <table> ALTER COLUMN embedding TYPE vector(<N>)`, and recreates the index with
  `CREATE INDEX <index> ON <table> USING hnsw (embedding vector_cosine_ops)`. Set
  `EMBEDDING_DIMENSION=<N>`, run `alembic upgrade head`, restart (the startup check compares both
  tables), and process the resumes and the jobs again.

### Analysis settings

The gap analysis (`POST /analyses`) reads four settings. They are listed in `.env.example`.

| Variable | Default | Meaning |
|---|---|---|
| `ANALYSIS_TOP_K` | 5 | Resume chunks kept per requirement (1-20) |
| `ANALYSIS_MIN_SIMILARITY` | 0.4 | Lowest cosine similarity a chunk may have (0-1); depends on the embedding model |
| `ANALYSIS_MAX_REQUIREMENTS_PER_CALL` | 8 | Requirements sent to the LLM in one call (1-50) |
| `ANALYSIS_MAX_LLM_CALLS` | 10 | LLM calls one analysis may make (1-100) |

## Resume processing API

Turn a stored resume into structured data and vectors (needs a configured LLM and embeddings).

```bash
curl -X POST localhost:8000/resumes/<id>/process    # 202, status "processing"; runs in the background
curl localhost:8000/resumes/<id>                    # poll: status, error, extraction
```

`status` is `uploaded` (stored, not processed), `processing`, `ready` or `failed`. A `ready` resume
has an `extraction`: the `resume` (summary, skills lines, experiences with `YYYY-MM` start/end,
bullets, education, languages, certifications, projects; no contact details), the
`total_experience_months` / `total_experience_years` (computed by the code from the dates, merging
overlapping jobs, never by the LLM), `warnings` (`dropped_unverified_items`,
`experiences_without_valid_dates`) and how it was made (`prompt_name`, `prompt_version`,
`llm_provider`, `llm_model`, `extracted_at`). Every bullet and skills line is the resume's own
wording, checked against the resume text; anything else is dropped. Each bullet and skills line
also becomes a vector chunk (`resume_chunk`, HNSW cosine index).

Processing again is allowed from any status except `processing`. A failed run keeps the previous
extraction and chunks. The work runs inside the API process: if the API restarts meanwhile, the
resume becomes `failed` with `processing_interrupted` at the next start (one API process is
assumed).

| Status | Code | When |
|---|---|---|
| 404 | `resume_not_found` | unknown id |
| 409 | `already_processing` | the resume is `processing` |
| 503 | `ai_not_configured` | no usable LLM or embeddings (status unchanged) |

A `failed` resume has `error.code`: `llm_auth_failed`, `llm_timeout`, `llm_unavailable` (rate limit
or server errors after retries), `llm_invalid_output`, `embedding_failed` (including a dimension
mismatch), `processing_interrupted` or `processing_failed`. Messages never contain resume text.

Tests marked `real_provider` call the provider configured in your environment; they are excluded
from the default run and from CI, and skipped when nothing is configured:

```bash
uv run --env-file .env pytest -m real_provider -rs
```

## Jobs API

The other half of the comparison: a job posting becomes a list of separate, searchable
requirements. Single user, no authentication. Needs a configured LLM and embeddings to be
processed (see "AI providers").

```bash
curl -X POST localhost:8000/jobs -H 'content-type: application/json' -d '{
  "title": "Senior Backend Engineer",
  "company": "ACME",
  "description": "We build payments. Requirements:\n- 5+ years of backend\n- Python is required\nNice to have:\n- Terraform",
  "requirements_text": null
}'                                                       # 201, status "uploaded"
curl localhost:8000/jobs                                 # all jobs, newest first, without the texts
curl localhost:8000/jobs/<id>                            # one job with its texts and extraction
curl -X DELETE localhost:8000/jobs/<id>                  # 204, also removes its requirements
curl -X POST localhost:8000/jobs/<id>/process            # 202, status "processing"; background
```

Fields: `title` (required, up to 200 characters), `company` (optional, up to 200), `description`
(required, the posting as free text, up to 50,000) and `requirements_text` (optional, up to 50,000;
for the "what the position needs" part when it is not inside the description). Text is trimmed, a
blank `company` or `requirements_text` is stored as null, unknown fields are rejected (422), and
posting the same text twice creates two jobs. Unknown ids answer 404 `job_not_found`.

Processing works exactly like resume processing: the same statuses (`uploaded`, `processing`,
`ready`, `failed`), the same error codes and messages, `404`, `409 already_processing` and
`503 ai_not_configured` (see "Resume processing API"), runs in the background, keeps the previous
results when a run fails, and marks jobs that were `processing` during a restart as `failed` with
`processing_interrupted`.

A `ready` job has an `extraction` with `job` (`seniority` `junior|mid|senior` or null, `language`
`en|pt|other`, `responsibilities`, `ats_keywords` and `requirements`), `warnings` and how it was made
(`prompt_name`, `prompt_version`, `llm_provider`, `llm_model`, `extracted_at`). Each requirement has:

| Field | Meaning |
|---|---|
| `id` | assigned by the code; the id of its row in `job_requirements` |
| `text` | a short statement of the demand; this is what gets embedded |
| `category` | `skill`, `years` (general experience, not tied to one technology), `language`, `education`, `domain` or `soft` |
| `priority` | `must_have` or `nice_to_have` |
| `priority_unclear` | true when the priority could not be decided and defaulted to `must_have` |
| `min_years` | the minimum years when the posting states a number (any category) |
| `keywords` | each with `name`, `normalized` (see `core/normalization.py`) and normalized `synonyms` |
| `source_text` | the posting's exact words for this requirement |

How priority is decided (English and Portuguese, accents and case ignored), in this order:
(1) cue phrases in the requirement's own text: `required`, `must`, `mandatory`, `obrigatório`,
`necessário`, `imprescindível`, `indispensável` mean must-have; `nice to have`, `a plus`, `preferred`,
`desirable`, `ideally`, `diferencial`, `desejável`, `será um plus`, `preferencialmente` mean
nice-to-have; a negated must-cue (`not required`, `não é obrigatório`) means nice-to-have; (2) the
heading of the section it sits in (`Requirements`, `Requisitos` versus `Nice to have`,
`Preferred qualifications`, `Diferenciais`); (3) the model's own judgment; (4) otherwise `must_have`
with `priority_unclear: true`. The model never overrides a cue found in the posting. The cue lists
live in `src/app/ai/extraction/priority.py`.

Every `source_text` and every responsibility is checked against the posting: the model gets one
correction round for the ones that are not there, and whatever is still invented is dropped.
`warnings` lists `dropped_unverified_items` (how many were dropped) and
`priority_unclear_requirements` (how many are flagged), when they are not zero.

Each requirement is also stored with its vector in `job_requirements` (HNSW cosine index, the
embedding model recorded), replaced as a whole on every successful run.

## Analyses API

The core of the product: for every requirement of a job, decide whether the resume satisfies it
and prove it. Single user, no authentication. It needs a **ready** resume, a **ready** job (both
processed with the same embedding model), the candidate profile (`PUT /profile`) and a configured
LLM (see "AI providers"). It never changes the resume, the job or the profile.

```bash
curl -X POST localhost:8000/analyses -H 'content-type: application/json' \
  -d '{"resume_id": "<resume id>", "job_id": "<job id>"}'
# 202 {"id": "...", "status": "processing", ...}  (or 200 with the stored result, see "Cache")
curl localhost:8000/analyses/<id>      # poll until "ready" (result) or "failed" (error)
```

A `ready` analysis has `result.findings`, one per requirement of the job in the job's order, and
`result.ats_coverage`, `result.warnings` and `result.provenance` (prompt version, LLM, embedding
model, number of LLM calls, settings used).

Each finding has the requirement's `priority` (and `priority_unclear`), a `verdict`, `evidence`,
an `explanation` and `decided_by`, the step that produced the verdict:

| `decided_by` | What it did |
|---|---|
| `deterministic` | Proved it in code: the keyword (or an alias such as `k8s`) is in the resume as a whole term, years computed from the resume's dates reach the minimum, the language level reaches the asked one. It only ever proves `met`; the only `missing` it gives is an education requirement when the resume has no education or certification entry. Keywords of one or two characters (`go`, `c`) never prove anything alone. |
| `semantic` | No resume chunk reached `ANALYSIS_MIN_SIMILARITY`: `missing`, without an LLM call. |
| `judge` | The LLM (batched, at most `ANALYSIS_MAX_REQUIREMENTS_PER_CALL` per call) answered `met`, `partial` or `missing` with 1-3 quotes. |
| `profile` | The resume does not (fully) show it but your profile does: `in_profile_not_in_resume`. This is the most actionable finding: add it to the resume. |

Verdicts: `met`, `partial`, `missing`, `in_profile_not_in_resume`. A `met` or `partial` verdict
always has 1-3 evidence quotes copied from the resume (`source: "resume"`), checked in code against
the resume text (whitespace, line breaks and a leading bullet are ignored; words, accents and case
are not): invented or reworded quotes are dropped, and an answer left without a valid quote becomes
`missing` with the flag `evidence_not_verbatim` and a fixed explanation. `in_profile_not_in_resume`
has `source: "profile"` evidence: a notable fact as written, or a statement made of your profile's
own values.

`ats_coverage` lists which of the job's ATS keywords appear literally in the resume text (`found`,
with the text as written) and which do not (`missing`). It is a literal check, like an ATS, and
only the resume counts. There is no score.

**Cache.** Asking again with the same inputs returns the stored analysis (HTTP 200) without
calling the LLM; while one is running you get it back with 202. A new analysis starts when anything
it reads changes: the profile, the resume or the job processed again, the judge prompt version, the
LLM provider or model, or an `ANALYSIS_*` setting. A `failed` analysis is never reused.

**Limits.** `ANALYSIS_MAX_REQUIREMENTS_PER_CALL` and `ANALYSIS_MAX_LLM_CALLS` (see "Analysis
settings") bound the tokens one analysis can spend. If the requirements that must be judged need
more calls than allowed, the analysis fails with `analysis_limit_exceeded` before any call.

Errors: `404` `resume_not_found`, `job_not_found`, `analysis_not_found`; `409` `resume_not_ready`,
`job_not_ready` (process them first), `profile_required` (save the profile),
`embedding_model_mismatch` (process the older of the resume and the job again); `503`
`ai_not_configured`; `422` for a bad body. A `failed` analysis has `error.code`: the processing
codes of resumes and jobs (`llm_auth_failed`, `llm_timeout`, `llm_unavailable`,
`llm_invalid_output`, `processing_interrupted`, `processing_failed`) plus `analysis_limit_exceeded`
and `embedding_model_mismatch`. Messages never contain resume, job or profile text.

**Tuning `ANALYSIS_MIN_SIMILARITY`.** The right value depends on the embedding model (0.4 is a
starting point for `bge-m3`). Too high gives many `missing` from retrieval; too low sends more
requirements to the LLM. Run the English and Portuguese cases against your model and read the
reported differences:

```bash
uv run --env-file .env pytest -m real_provider tests/real_provider/test_gap_analysis.py -rs -W default
```

## Repository settings (manual)

Workflows cannot apply these GitHub settings; configure them once under Settings:

- Protect the `main` branch.
- Require pull requests and disallow direct pushes to `main`.
- Require the status checks `lint`, `typecheck`, `test`, `integration` and `docker-build`
  (CI), plus the PR-rules checks `title` and `commits`.
- Allow squash merging only, using the pull request title as the commit message.

Renaming a job silently removes it from the required checks, so keep the names above.
