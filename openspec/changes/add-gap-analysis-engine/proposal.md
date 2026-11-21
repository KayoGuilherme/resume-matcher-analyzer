# Proposal

## Why

A resume and a job can now both be turned into structured, verbatim, searchable pieces, but nothing compares them yet. This is the core of the product: for every requirement of a job, decide whether the resume satisfies it and prove it with a quote from the resume, so the candidate sees exactly what an AI/ATS screening would miss. The most useful finding is a requirement the resume fails to show but the candidate's own profile says they have.

## What Changes

- **Analyses API** (`src/app/analyses/`): `POST /analyses` (`resume_id`, `job_id`) and `GET /analyses/{id}`. The analysis runs in the background with a status (`processing` -> `ready` | `failed`) and the same safe error reporting as resume and job processing. It is only accepted when the resume and the job are `ready` and the candidate profile exists.
- **Four steps per requirement** (`src/app/ai/matching/`), run in order, each able to settle the verdict:
  1. *Deterministic checks*: literal keyword match with aliases and synonyms, years of experience computed from the resume's dates (and compared with the profile), language level from the resume and the profile, and the required section present. Only positive proofs decide (`met`); the absence of a literal match never does.
  2. *Semantic retrieval*: the top-k resume chunks by cosine similarity to the requirement, above a minimum similarity (both in config). No similar content at all settles the requirement as `missing` without spending tokens.
  3. *LLM judge*: batched, temperature 0, verdict `met` / `partial` / `missing` with 1-3 evidence quotes copied from the resume.
  4. *Profile cross-check*: when the resume does not (fully) show a requirement but the profile does, the verdict is `in_profile_not_in_resume`.
- **Verbatim evidence enforced in code**: every quote the judge returns is checked against the resume text; a `met` or `partial` answer without a valid quote becomes `missing`.
- **ATS keyword coverage**: which of the job's ATS keywords appear literally in the resume text, and which do not.
- **Result per requirement**: verdict, priority (from the job), evidence, explanation, and the step that decided it (`deterministic`, `semantic`, `judge`, `profile`).
- **Cache**: an analysis for the same inputs (resume, job, prompt version and the inputs that shape the result) is returned instead of being run again.
- **Limits**: configurable top-k, minimum similarity, requirements per LLM call and total LLM calls per analysis (`ANALYSIS_*` settings).
- **Storage**: a new `analysis` table (migration `0006`) holding the status, the cache key and the whole result; deleting a resume or a job deletes its analyses. Interrupted analyses are marked `failed` at startup, like resumes and jobs.
- **Small additions to existing features** (no behavior change to their API): read access to a resume's chunks with their vectors and to a job's requirement vectors, and the alias inverse in `core/normalization.py` used for literal matching.

Out of scope: a score, a final decision (pass / fail), rewrite suggestions, editing or deleting analyses, listing analyses, a UI, re-running only part of an analysis.

## Capabilities

### New Capabilities
- `analysis-management`: `POST /analyses` and `GET /analyses/{id}`, preconditions, status lifecycle and failure codes, background execution, cache, call limits, storage and deletion with its resume or job, privacy of logs.
- `requirement-matching`: the four steps and their rules, the verdicts and the deciding step, verbatim evidence enforced in code, the result shape per requirement.
- `ats-keyword-coverage`: literal presence of the job's ATS keywords in the resume text, with aliases.

### Modified Capabilities
- `app-configuration`: four new settings (`ANALYSIS_TOP_K`, `ANALYSIS_MIN_SIMILARITY`, `ANALYSIS_MAX_REQUIREMENTS_PER_CALL`, `ANALYSIS_MAX_LLM_CALLS`), added as a requirement, documented in `.env.example`.

## Impact

- **Code**: new `src/app/analyses/` (router, schemas, models, repository, service, startup), new `src/app/ai/matching/` (models, errors, text matching, language levels, deterministic, retrieval, judge, profile check, ATS coverage, cache key, engine), `src/app/ai/prompts/gap_judge.md`, new error codes in `core/processing.py` and `ai/error_codes.py`, new settings in `core/config.py`, read methods in `resumes/repository.py` and `jobs/repository.py`, `aliases_of` in `core/normalization.py`, `src/app/main.py` (router and startup), `alembic/env.py`; migration `0006`.
- **API**: new `/analyses` endpoints only; no existing endpoint changes.
- **Dependencies**: none (cosine similarity is plain Python in a threadpool; no new package).
- **Docs**: README (analyses API, the four steps, settings, error codes, tuning the similarity threshold), `.env.example`, `.claude/CLAUDE.md` (the new `analyses/` and `ai/matching/` folders).
- **Operations**: `alembic upgrade head` applies `0006`. The change builds on `add-ai-foundation-and-resume-extraction` and `add-job-positions`, which must be merged first (migration `0005`, `job_requirements`, `resume_chunk`).
