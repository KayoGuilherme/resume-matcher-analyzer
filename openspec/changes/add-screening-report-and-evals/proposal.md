# Proposal

## Why

The gap analysis says, requirement by requirement, what the resume shows and what it does not. The candidate still has to answer two questions by hand: *will a first-step AI screener probably let this resume through?* and *what exactly do I change first?* This change turns the analysis into that answer, and adds the measurements (evals) that tell us whether the answers can be trusted, before anyone relies on them.

## What Changes

- **Score** (`src/app/ai/matching/score.py`, no LLM): weighted coverage of the must-haves, the nice-to-haves and the job's ATS keywords, minus penalties for resume parsing-quality issues, giving a number from 0 to 100 and an outcome `likely_pass` | `borderline` | `likely_reject`. A `met` counts fully, a `partial` counts a configured fraction, and `missing` and `in_profile_not_in_resume` count nothing, because a screener reads only the resume. Weights, penalties and thresholds are settings (`SCORE_*`). The breakdown is part of the answer.
- **Screener simulation** (`screener.py`, prompt `screener.md`): an LLM with a rubric acts as a first-pass screener. It sees the resume text and the job's requirements and keywords, never the profile or the verdicts. It returns a decision (`pass` | `borderline` | `reject`) and reasons, is run `SCREENER_RUNS` times (default 3), and the report gives the majority decision and the consistency (share of runs that agree). Every report carries a disclaimer that this simulates, and cannot see, the company's real ATS.
- **Rewrite suggestions** (`rewrites.py`, prompt `rewrite_suggestions.md`): for the requirements the profile proves but the resume omits, for partial ones and for ATS keywords the profile proves, an LLM proposes a reworded or new bullet. Each suggestion points to the resume bullet or profile fact it is based on (resolved in code, not typed by the model). A deterministic check rejects any suggestion with a technology, a number or a year that is in neither the resume nor the profile; rejected suggestions are never shown, only counted.
- **Report** (`GET /analyses/{id}/report`, JSON by default, `?format=markdown`): the disclaimer, the score with its breakdown, the screener result, the ATS keyword coverage, the suggestions and a prioritized list of actions in three kinds, in this order: fix parsing/format issues, add what the profile proves but the resume omits, and real skill gaps that rewriting cannot honestly fix (said plainly).
- **Analysis run extended**: after the gap analysis the same background run executes the screener and the suggestions and stores them with a snapshot of the resume's parsing issues, in a new `report` column (migration `0007`). The analysis becomes `ready` only when both are stored; any LLM failure fails the analysis with the usual safe codes, and a new request retries it. The score, the actions and the Markdown are computed when the report is read, from stored data and the current `SCORE_*` settings, so tuning weights needs no new LLM calls.
- **Settings**: `SCORE_WEIGHT_MUST_HAVE`, `SCORE_WEIGHT_NICE_TO_HAVE`, `SCORE_WEIGHT_KEYWORDS`, `SCORE_PARTIAL_CREDIT`, `SCORE_PENALTY_CRITICAL`, `SCORE_PENALTY_WARNING`, `SCORE_PENALTY_INFO`, `SCORE_PASS_THRESHOLD`, `SCORE_BORDERLINE_THRESHOLD`, `SCREENER_RUNS`, `REPORT_MAX_SUGGESTIONS`, all validated at startup and listed in `.env.example`.
- **Evals** (`evals/`): 12 synthetic resume/job/profile cases, 6 in Portuguese and 6 in English, each with the expected verdict of the requirements that matter and the expected outcome, and a runner `uv run python -m evals.run` that runs the real pipeline and reports requirement-verdict accuracy, outcome accuracy, fabricated-evidence rate (must be 0) and consistency across runs. It exits with an error when a metric is below its configured threshold (`EVAL_*`). It uses the configured real providers, is run locally, never in CI, and is documented in the README.

Out of scope: a UI, authentication, deployment, multi-user support, job-market statistics, a PDF or DOCX export of the report, editing the resume file, listing analyses, and re-running only the report of an analysis.

## Capabilities

### New Capabilities
- `screening-score`: the deterministic score, its weighted components, the parsing penalties, the outcome and its thresholds.
- `screener-simulation`: the rubric-based first-pass screener, repeated runs, majority and consistency, what it may and may not see, and the always-present disclaimer.
- `rewrite-suggestions`: suggestions for bullets, their provenance pointer, and the deterministic rejection of invented technologies, numbers and years.
- `analysis-report`: `GET /analyses/{id}/report` in JSON and Markdown, the prioritized actions, how the report is produced inside the analysis run, stored, cached and read.
- `evaluation-harness`: the dataset, the runner, the metrics, the thresholds and the exit status.

### Modified Capabilities
- `app-configuration`: new settings for the score, the screener and the report, added as a requirement and documented in `.env.example`.

## Impact

- **Code**: new files in `src/app/ai/matching/` (`score.py`, `screener.py`, `rewrites.py`, `technologies.py`, `actions.py`, `report.py`, `markdown.py`, `report_models.py`), prompts `src/app/ai/prompts/screener.md` and `rewrite_suggestions.md`; in `src/app/analyses/`: the endpoint in `router.py`, the report step in `service.py`, `report` read/write in `repository.py`, the column in `models.py`, response models in `schemas.py`; settings in `core/config.py`; the cache key in `ai/matching/cache.py`; migration `0007`; new top-level package `evals/` (dataset and runner) and `tests/evals/`. No new folder under `src/app/`.
- **API**: one new endpoint, `GET /analyses/{id}/report`. `POST /analyses` and `GET /analyses/{id}` keep their shapes; an analysis now takes longer to become `ready` and uses more LLM calls (`SCREENER_RUNS` plus at most one for suggestions, on top of the judge's, and not counted in `ANALYSIS_MAX_LLM_CALLS`).
- **Dependencies**: none.
- **Docs**: README (report API, score formula and tuning, screener caveats, running the evals), `.env.example`, `.claude/CLAUDE.md` (the new files and `evals/` layout).
- **Operations**: `alembic upgrade head` applies `0007`. The change builds on `add-gap-analysis-engine`, which must be merged first (migration `0006`, `analysis` table, `AnalysisResult`). Eval runs spend real tokens and send the synthetic resumes to the configured provider.
