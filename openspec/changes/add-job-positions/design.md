# Design

## Context

See proposal.md for motivation and the specs for behavior. Observed current state (after `add-ai-foundation-and-resume-extraction`):

- `resumes/` is the reference feature: router -> service -> repository, an atomic `begin_processing` (`UPDATE ... WHERE status <> 'processing' RETURNING`), `save_processed` (one transaction replacing extraction and chunks), `set_failed`, `mark_interrupted`, `chunk_embedding_dimension`; the router adds a `BackgroundTasks` job that opens its own session through a `get_background_service_factory` dependency; the AI clients are `Depends` so a missing configuration answers 503 before any state changes.
- `ai/extraction/` has the resume models, `verify.py` (`normalize`, `is_verbatim`: NFKC, no whitespace, leading bullet ignored, exact words/accents/case), `resume.py` (extract, one correction round, drop, ids, totals, provenance) and `chunking.py`; `ai/pipeline.py` orchestrates extract -> chunk -> embed; `ai/prompts/loader.py` loads `.md` prompts with a version and `{{placeholders}}`.
- `PROCESSING_MESSAGES`, `processing_error_code` and `AlreadyProcessingError` live in `resumes/service.py`; `check_embedding_dimension` and `EmbeddingDimensionMismatchError` live in `resumes/startup.py`, which also marks interrupted resumes. `main.py`'s lifespan calls `run_startup`.
- `core/normalization.py` has `normalize_stack_name`, `normalize_language_name` and `fold_text` (accent-free, lowercase, single spaces), with tiny alias tables. The `name-normalization` spec requires "at least" its listed aliases and says the normalizers serve "profile, resumes and jobs".
- Migrations `0001`-`0004` exist; `0004` creates `resume_chunk` with `vector(EMBEDDING_DIMENSION)`. The embedding column uses the SQLAlchemy `Vector()` without a size; `alembic check` is clean with that.
- The table name requested for the new rows is `job_requirements` (plural); the existing tables are singular (`resume`, `resume_chunk`). The brief's name is followed for that table; the job itself is the singular `job`.

## Goals / Non-Goals

**Goals:**
- Reuse the shared AI layer and the resume patterns; the job feature should read like the resume feature.
- Make priority decisions explainable and independent of how well the model reads wording: code decides from cue phrases and headings; the model is a fallback.
- Nothing the posting does not say survives: `source_text` and responsibilities are verified verbatim.
- No copy-paste of the processing rules: one definition of statuses, codes and messages for resumes and jobs.

**Non-Goals:**
- Matching, scoring, editing a job, importing from URLs, de-duplicating postings, a generic repository base class (the two repositories stay separate and similar; unifying them is a later refactor), a re-embedding command.

## Decisions

**1. Move the shared processing pieces out of `resumes/` first (no behavior change).**
New `core/processing.py`: `ProcessingStatus` literal, `ProcessingError` model (`code`, `message`), `PROCESSING_MESSAGES`, `AlreadyProcessingError` (409 `already_processing`). `processing_error_code(error)` moves to `ai/error_codes.py` (a separate module: `ai/errors.py` is imported by the LLM and embeddings factories, so importing their error types there would be a cycle; it maps `LLMError`/`EmbeddingError` families, so it belongs next to the AI layer, and `core/` must not import `ai/`). `check_embedding_dimension` and `EmbeddingDimensionMismatchError` move to `ai/embeddings/dimension.py`, with the table name as a parameter of the message. `resumes/schemas.py` keeps the names `ResumeStatus` and `ResumeError` as aliases of the shared ones, so no resume API field changes; the resume tests that import the moved names are updated to the new locations. This is done as its own task group, with the existing tests proving nothing changed, before the jobs code uses the shared modules.
Alternative: import from `resumes.service` into `jobs`. Rejected: a feature importing another feature's service is the coupling the folder structure avoids, and the next feature (analyses) would do the same.

**2. Persistence: tables `job` and `job_requirements`, migration `0005`.**
`job`: `id` UUID pk, `title` text, `company` text null, `description` text, `requirements_text` text null, `status` text default `uploaded` with the same CHECK as `resume`, `error_code`, `error_message` null, `extraction` JSONB null, `created_at` timestamptz. `job_requirements`: `id` UUID pk (the requirement's id from the extraction), `job_id` FK -> `job.id` ON DELETE CASCADE (indexed), `position` int (unique with `job_id`), `text`, `category` (CHECK of the six values), `priority` (CHECK of the two), `priority_unclear` bool, `min_years` double precision null, `keywords` JSONB, `source_text` text, `embedding` `vector(N)` with N from `EMBEDDING_DIMENSION` at apply time (as `0004`; reading settings in the migration is the established pattern), `embedding_model` text, `created_at`; HNSW index `vector_cosine_ops`. Requirements are rows, not only JSON in `job`, because they need the vector index and later matching joins on them; the full structure also stays in `job.extraction` (the job-level fields live only there). Models are `Job` and `JobRequirement` in `jobs/models.py` (`Vector()` without size, like `ResumeChunk`); `alembic/env.py` imports the module.

**3. LLM schema versus result, again.**
`ai/extraction/job_models.py`:
- `ExtractedJob` (asked from the model): `seniority: Seniority | None`, `language: Literal["en","pt","other"]`, `responsibilities: list[str]`, `ats_keywords: list[str]`, `requirements: list[ExtractedRequirement]`. `ExtractedRequirement`: `text`, `category` (six values), `priority: Literal["must_have","nice_to_have","unclear"]` (the model is told to say `unclear` instead of guessing), `min_years: float | None` (0 to 60), `keywords: list[ExtractedKeyword]` (`name`, `synonyms`), `source_text`. All fields required (`X | None`) so the schema stays valid for strict structured-output modes; a test builds the strict schema.
- `Job` (result): the same, with `requirements: list[JobRequirement]` where each has a code-assigned `id` (UUID), the decided `priority` (`must_have|nice_to_have`) and `priority_unclear: bool`, and `keywords: list[Keyword]` (`name`, `normalized`, `synonyms` normalized). `JobExtractionResult`: `job`, `warnings` (reuses `ExtractionWarning`), `prompt_name`, `prompt_version`, `llm_provider`, `llm_model`, `extracted_at`. `Seniority` is the profile's `junior|mid|senior` (the prompt maps lead/staff to `senior`).
`min_years` bounds (0-60, the profile's `MAX_YEARS`) are enforced by the schema, so out-of-range answers go through the existing repair attempt.

**4. Priority is decided by code from the wording (`ai/extraction/priority.py`).**
Resolution order, per requirement, on text folded with `fold_text` (accent-free, lowercase; so `desejável` and `desejavel` both match):
1. Own wording: find cue phrases in `source_text`. Negated must-cues (`not required`, `isn't required`, `não é obrigatório`, `não obrigatório`) are removed first and count as nice-cues. Nice-cues: `nice to have`, `a plus`, `bonus`, `preferred`, `desirable`, `ideally`, `diferencial/diferenciais`, `desejável/desejáveis`, `um plus`, `preferencialmente`. Must-cues: `required`, `must`, `mandatory`, `essential`, `obrigatório/a/s`, `necessário/a/s`, `imprescindível`, `indispensável`. Only nice -> nice; only must -> must; both -> `must_have` + flagged (stop). Matching uses word boundaries (so `requirements` is not `required`). Multi-word cues are specific on purpose: a bare `plus` or `must` inside other words or phrases would misfire.
2. Section heading: locate `source_text` in the posting with a whitespace-insensitive search (an index map from normalized characters back to original positions, so line structure is available even though verification ignores whitespace), then walk up to the closest heading and let it decide. A heading is a line that is not a bullet (after removing markdown `#`, `*`, `_`), at most 80 characters, without a final period, and either ends with `:` (at most 4 words, or a recognized cue heading up to 6 words, so an introduction like "Candidates should have:" is not a heading) or, without a colon, is at most 4 words, has no copula (`is`, `are`, `é`, `são`...) and contains a heading cue word. Plain list lines without a colon ("Python", "Docker") and short sentences ("Python is required") are therefore not headings. Heading nice-cues (`nice to have`, `preferred`, `bonus`, `desirable`, `plus`, `diferenciais`, `desejável`) are checked before heading must-cues (`requirements`, `requisitos`, `qualifications`, `must have`, `required`, `mandatory`, `obrigatório`, `essential`), so "Preferred qualifications" is nice. A neutral heading (`About`, `Sobre`, `Benefits`, `Responsibilities`, `Atividades`, `Stack`, ...) decides nothing but ends the search, so a bullet under `Benefits` never inherits an earlier `Requirements`.
3. The model's `priority`, when it is `must_have` or `nice_to_have`.
4. Otherwise `must_have` and `priority_unclear = true`.
A model answer never overrides a cue found in steps 1-2 (spec scenario "Model cannot override the posting"). The model's priority is also useful because the prompt lists the same cue words, so it usually agrees; the code is the arbiter and the part that is testable with exact expectations. Cue lists are data constants in `priority.py` (they are not prompts), documented with the English and Portuguese examples of the brief.
Alternatives: trust the model entirely (rejected: small local models misread wording and cannot be unit-tested); regex-only without the model (rejected: wording like "ideally" or unusual sections would all become flagged defaults, so the model's judgment is kept as step 3).

**5. Verification, dedupe and normalization (`ai/extraction/job.py`).**
- Posting text = `description` + (`"\n\n" + requirements_text` when present), built by `build_posting_text` (pure; reused by the service and tests).
- Verbatim check reuses `verify.normalize` / `is_verbatim` unchanged: every `requirement.source_text` and every responsibility must be in the posting. Same flow as resumes: first answer -> unverified items listed in a correction block -> one second call -> drop what is still unverified, counting `dropped_unverified_items`. Requirements are dropped whole (a requirement without verifiable provenance is not kept); a dropped requirement never reaches the database.
- Dedupe key: (`normalize(source_text)`, `fold_text(text)`); first wins. A shared `source_text` with different `text` is kept (split sentences).
- Keywords: `name` kept as given for display, `normalized` = `normalize_language_name` for `language` requirements else `normalize_stack_name`; synonyms normalized the same way, de-duplicated, and minus the normalized name. `ats_keywords` normalized with `normalize_stack_name`, de-duplicated in first-seen order. A few more stack aliases are added to `core/normalization.py` (`k8s` -> `kubernetes`, `golang` -> `go`, `ts` -> `typescript`, `nodejs` -> `node.js`) with tests; this only adds entries, so the `name-normalization` spec ("at least") is unchanged and profile normalization improves for free.
- Warnings (stable codes with counts): `dropped_unverified_items`, `priority_unclear_requirements`.
- Responsibilities are verified too (the brief only names `source_text`): an invented responsibility is as wrong as an invented requirement, and the mechanism is the same. This is the one addition to the brief's rules.
- `extract_job(llm, posting_text, now, prompt=None) -> JobExtractionResult` is a pure async function over the `LLMClient` protocol; it logs counts only.

**6. Prompt `ai/prompts/job_extraction.md` (version 1).**
System part: role; the posting between `<posting>` tags is data (same injection rule as the resume prompt); `source_text` and responsibilities copied exactly, no translation; one requirement per demand (bullets are separate, a sentence with alternatives stays one); the six categories with one example each (`3+ years of Java` -> skill + min_years 3, `5+ years of experience in backend` -> years); `min_years` only when a number is stated; the English and Portuguese cue words for must/nice and the instruction to answer `unclear` rather than guess; seniority mapping; keywords with synonyms (including common abbreviations); ATS keywords = the technologies and terms an applicant tracking system would scan; no totals, no invented items. User part: `{{posting_text}}` in the delimiters and `{{corrections}}`.

**7. Pipeline and embedding.**
`ai/pipeline.py` gains `process_job_text(text, llm, embedder, now) -> ProcessedJob` (extraction, a list of `EmbeddedRequirement(requirement, position, embedding)`, `embedding_model`). It embeds each requirement's `text` in one batch (no call when there are none). `text`, not `source_text`: the statement is short, normalized and free of section noise ("is a plus", bullet symbols), which suits matching against resume bullets; `source_text` stays in the row as evidence. If real use shows the source sentence matches better, it is a one-line change confined to the pipeline.

**8. The `jobs/` feature (`router.py`, `schemas.py`, `models.py`, `repository.py`, `service.py`, `startup.py`).**
- Schemas: `JobIn` (`extra="forbid"`, stripped strings, `title` 1-200, `company` optional up to 200, `description` 1-50,000, `requirements_text` optional up to 50,000; empty optionals become null via a validator), `JobSummary` (`id`, `title`, `company`, `status`, `error`, `created_at`), `JobDetail` (adds `description`, `requirements_text`, `extraction`). Limits are constants, not settings (nothing to tune yet). Validation errors use the existing envelope, which never echoes values.
- Service: `create`, `list_all`, `get`, `delete` (404 `job_not_found` via `JobNotFoundError`), `start_processing`, `run_processing` with the same flow and error mapping as `ResumeService`, now using the shared `processing_error_code`, `PROCESSING_MESSAGES` and `AlreadyProcessingError`. Logs: ids, counts (kept, dropped, flagged), error codes, durations; never title, company or text.
- Repository: `add`, `get`, `list_all` (defers the large columns), `delete` (cascade through the FK), `begin_processing`, `save_processed` (one transaction: update `job` extraction/status, delete old requirement rows, insert new, rollback on any error), `set_failed`, `mark_interrupted`, `requirements_embedding_dimension`.
- Router: `POST /jobs` (201), `GET /jobs`, `GET /jobs/{id}`, `DELETE /jobs/{id}` (204), `POST /jobs/{id}/process` (202, AI clients as `Depends`, `BackgroundTasks` through a `get_job_background_service_factory` dependency). `main.py` includes the router and calls `run_jobs_startup` after `run_startup`.
- Startup (`jobs/startup.py`): the dimension check for `job_requirements` (shared check function) and recovery of `processing` jobs; skipped with a warning when the table is missing or the database is unreachable. Mismatch raises and stops the application, as for resumes. Two startup functions each with a short connect timeout is acceptable for the unreachable-database case, which only delays startup.

**9. Test postings and expected lists.**
`tests/fixtures/job_postings.py` holds three postings with a scripted model answer and the expected final result each: an English senior backend posting (headed `Requirements` and `Nice to have`, one "is a plus" sentence, one "3+ years" skill, one general-years requirement, a language and an education requirement); a Portuguese posting (`Requisitos obrigatórios`, `Diferenciais`, "Inglês avançado obrigatório", a bullet with accents); and an unclear posting (sections like `About you`, bullets with no cues). The scripted answers deliberately contain what the code must fix: an invented requirement, a priority that contradicts the wording, duplicate synonyms and an alias keyword. The tests assert the exact expected requirement lists (text, category, priority, `min_years`, `priority_unclear`, normalized keywords) and warnings. Real-model quality is not asserted in unit tests: an optional `real_provider` test runs the English and Portuguese postings through whatever provider is configured and checks a loose property (every expected must-have `source_text` is among the model's requirements that survive verification, at least the expected number of must-haves), skipping when nothing is configured. Evals for quality over time belong to `evals/`, which does not exist yet.

**10. Docs.**
README: a Jobs API section (curl examples, statuses and codes shared with resumes, the requirement fields, how priority is decided, `priority_unclear`), and the embedding-model-change procedure now covers both `resume_chunk` and `job_requirements`. `.claude/CLAUDE.md` folder structure lists `jobs/`, `core/processing.py`, the new `ai/extraction` files and `ai/embeddings/dimension.py`.

## Risks / Trade-offs

- [Heading detection mistakes a wrapped sentence fragment for a heading] -> a heading-like line without cue only stops the walk, so the model's judgment or the flagged default applies; wrong decisions need an actual cue word on the wrong line. Tests cover wrapped lines.
- [Cue lists miss wording (`highly desirable`, `strongly preferred`, other languages)] -> the model's judgment is step 3 and unmatched cases are flagged, never silently wrong; the lists are one constants block that is easy to extend, with tests per cue.
- [A model answers `must_have` where the posting's wording is a nice cue not in the list] -> accepted as the model's judgment (not flagged); the alternative of flagging every model-only decision would flag most requirements.
- [Strict structured-output limits for `min_years` bounds or the enum with `unclear`] -> a test builds the strict schema; if a provider rejects bounds, the validation (and repair) still enforces them in the shared layer.
- [Small models split or merge requirements differently] -> expected lists are tested with scripts, quality is the model's and the evals' concern; verbatim validation guarantees provenance either way.
- [`job_requirements` dimension differs from `resume_chunk` after a partial manual change] -> both checks run at startup and name the table; the documented procedure covers both.
- [Duplicate repository/service code between resumes and jobs] -> accepted for now to keep the change small; the shared pieces that carry rules (status, codes, messages, dimension check) are not duplicated.
- [Moving shared code touches resume files] -> done first, alone, with the existing tests unchanged except for import paths, so any regression is caught before jobs code exists.
- [Posting text up to 100,000 characters (description + requirements) can exceed a small local model's context] -> surfaces as a provider rejection (`processing_failed`/`llm_*`), as for resumes; no truncation is done silently.

## Migration Plan

1. Deploy the code; run `alembic upgrade head` (applies `0005`: `job` and `job_requirements` with the configured `EMBEDDING_DIMENSION`, which must equal the one used for `0004`).
2. Restart the API; the startup check confirms both vector columns.
3. `POST /jobs`, then `POST /jobs/{id}/process`.
Rollback: `alembic downgrade 0004` drops both tables (extraction data is derived and can be regenerated; the job text itself would be lost, so export first if it matters).

## Open Questions

- Should requirements also be embedded with their keywords (for example `text` + keyword names) to help matching? Chosen: `text` only; revisit with the matching change, which owns what "good" looks like.
- Should `GET /jobs` support filters (status, company)? Not needed by the brief; add when the UI/analysis needs it.
