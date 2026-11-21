# Proposal

## Why

A resume can now be turned into structured, verbatim, searchable pieces. The job posting is the other half of the comparison, and today it is just free text. Before anything can be matched or scored, each posting has to become a list of clean, separate, searchable requirements, each saying what is asked, how strongly, and exactly where in the posting it comes from.

## What Changes

- **Job positions** (`src/app/jobs/`): `POST /jobs` (title, optional company, description, optional requirements text), `GET /jobs`, `GET /jobs/{id}`, `DELETE /jobs/{id}`. A new job is `uploaded`.
- **Processing**: `POST /jobs/{id}/process` with the same status flow, background execution, error codes and 202/404/409/503 behavior as resumes (`uploaded -> processing -> ready | failed`).
- **Extraction** through the shared AI layer into a `Job` model: seniority, language of the posting, responsibilities, ATS keywords and a list of requirements. Each requirement has its text, a category (`skill`, `years`, `language`, `education`, `domain`, `soft`), a priority (`must_have` or `nice_to_have`), the minimum years if any, keywords with synonyms, and the exact `source_text` from the posting.
- **Priority from the wording**, in English and Portuguese (`required` / `obrigatório` vs `nice to have` / `diferencial` / `desejável`), decided mainly by code from cue phrases in the requirement's own text and in the section heading above it, with the model's judgment as the fallback. When it is unclear the requirement is `must_have` and flagged `priority_unclear`.
- **Verbatim validation**: every requirement's `source_text` (and every responsibility) must appear in the posting; the model gets one correction round and whatever is still invented is dropped and counted in the warnings.
- **Normalization** of keywords, synonyms and ATS keywords with the existing `core/normalization.py` (stack names, and language names for language requirements).
- **Storage**: each requirement is embedded and stored in a new `job_requirements` table (pgvector, HNSW cosine index, embedding model recorded), replaced as a whole on every successful run. Startup checks its vector size like it does for resume chunks.
- **Shared code instead of copies**: the processing status, error codes and messages, the "already processing" error and the embedding-dimension check move from the resumes feature to shared modules, with no change in resume behavior.
- **Tests**: English and Portuguese test postings with expected requirement lists, run through fakes only; a `real_provider` test compares a real model against the same lists.

Out of scope: matching a job against a resume, scoring, editing a job after creation, fetching a posting from a URL, de-duplicating postings, a dedicated re-embedding command.

## Capabilities

### New Capabilities
- `job-management`: creating, listing, reading and deleting job positions, with input limits and privacy rules.
- `job-extraction`: the structured `Job` model, how priority is decided from the wording (English and Portuguese), verbatim validation of `source_text`, keyword normalization and provenance.
- `job-requirements`: the `job_requirements` table with one embedded row per requirement, replacement as a whole, deletion with the job, and the startup vector-size check.
- `job-processing`: the status lifecycle and `POST /jobs/{id}/process`, with the same failure codes and recovery as resume processing.

### Modified Capabilities
<!-- None. Resume behavior does not change: the shared pieces are moved, not altered. The existing name-normalization requirements ("at least" these aliases) allow a few more aliases without a spec change. -->

## Impact

- **Code**: new `src/app/jobs/` (router, schemas, models, repository, service, startup), `src/app/ai/extraction/` files for jobs (models, priority cues, verification, extraction, chunk-less requirement building), `src/app/ai/prompts/job_extraction.md`, `process_job_text` in `src/app/ai/pipeline.py`, a few more aliases in `src/app/core/normalization.py`; migration `0005` (tables `job`, `job_requirements`); `src/app/main.py` (router and startup) and `alembic/env.py`.
- **Refactor of existing code (no behavior change)**: the status type, error codes/messages, `AlreadyProcessingError` and `check_embedding_dimension` move to `app/core/processing.py` and `app/ai/embeddings/dimension.py`; the resumes feature imports them from there.
- **API**: new `/jobs` endpoints only; no existing endpoint changes.
- **Dependencies**: none. Config: none (limits are constants).
- **Docs**: README (jobs API, error codes), `.claude/CLAUDE.md` (the new folder and files).
- **Operations**: `alembic upgrade head` applies `0005`, creating `job_requirements` with the configured `EMBEDDING_DIMENSION` (it must equal the dimension of `resume_chunk`).
