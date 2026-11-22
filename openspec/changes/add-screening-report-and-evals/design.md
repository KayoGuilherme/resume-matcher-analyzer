# Design

## Context

See `proposal.md` for the motivation. This change sits on `add-gap-analysis-engine` (not merged yet when this was written; it must be merged first). What that change gives us and what we rely on:

- `analyze()` (`ai/matching/engine.py`) returns an `AnalysisResult`: findings with verdicts (`met`, `partial`, `missing`, `in_profile_not_in_resume`), evidence, `ats_coverage` (found with matched text, missing), warnings and provenance. It is pure and takes an `LLMClient`; the profile cross-check already exists.
- `AnalysisService.run()` runs it in the background and stores the result in the `analysis` row (`result` JSONB, one active row per cache key). Failures become `failed` with codes from `ai/error_codes.py`.
- The resume's parsing issues (`ParsingIssue`: code, severity `critical|warning|info`, message) exist since upload and are in `ResumeDetail.issues`; nothing uses them in the analysis yet.
- `ai/pipeline.py` has `process_resume_text` / `process_job_text` (extract, chunk, embed, no DB), which the evals can call directly. `FakeLLMClient` and `FakeEmbeddingClient` exist for tests.
- The LLM client has no per-call temperature: it uses `LLM_TEMPERATURE` (default 0). `JobInput` has the requirements, ATS keywords and language; it has no raw posting text.
- Rules from `.claude/CLAUDE.md` that shape this design: no new folder under `src/app` without asking, prompts only as versioned `.md` files, everything the LLM returns is a Pydantic model, evidence must be verifiable, never fabricate resume content, no resume text in logs, no network in tests, evals separate from unit tests.

## Goals / Non-Goals

**Goals:**
- One explainable number and outcome, one simulated screener opinion with its disagreement visible, and an ordered list of actions that is honest about what rewriting cannot fix.
- Make "never fabricate" a property of code (a deterministic check), not of a prompt.
- Make quality measurable: a command that fails when a metric regresses.

**Non-Goals:**
- A calibrated probability of passing a real ATS. The score is a heuristic and the screener a simulation; the report says so.
- Re-running only the report, listing analyses, or exporting files.
- Making the screener independent of the judge model (it uses the same configured LLM).

## Decisions

### 1. New code goes into the existing folders
`score.py`, `screener.py`, `rewrites.py`, `technologies.py`, `actions.py`, `report.py`, `markdown.py` and `report_models.py` go into `ai/matching/` (pure, no DB, no HTTP, only the `LLMClient` protocol), the prompts into `ai/prompts/`, the endpoint and storage into the existing `analyses/` files. `evals/` and `tests/evals/` are the only new top-level folders, and `evals/` already exists in the documented layout.
*Alternative:* a new `ai/reporting/` package. Cleaner naming, but the project rule says not to change the folder structure without asking; if this grows, moving the files is a mechanical follow-up.

### 2. What is stored and what is computed on read
Stored, in a new nullable `report` JSONB column of `analysis` (migration `0007`), written in the same statement as `result`: the screener runs, the accepted suggestions, the rejection counts, the job language, the ATS keywords that are profile stacks, a snapshot of the resume's parsing issues and the provenance of the report. Computed on every read: the score and outcome, the actions and the Markdown.
Why: everything that costs tokens, or reads the profile or the resume row (which can change later), is frozen with the analysis; everything that is pure arithmetic over frozen data follows the current `SCORE_*` settings, so weights and thresholds can be tuned (and the evals' thresholds calibrated) without paying for the LLM again. The cache key therefore includes the screener and suggestion prompts and versions, `SCREENER_RUNS` and `REPORT_MAX_SUGGESTIONS`, and excludes `SCORE_*`.
*Alternatives:* store the whole report (immutable, but every threshold change needs a new analysis and new tokens); compute everything on read (would need the current profile and resume, so a report could silently change when the profile is edited).
*Consequence:* `AnalysisDetail` is unchanged. `ready` means result and report are both stored; analyses made before this change have no report (`404 report_not_available`) and can never be returned by `POST /analyses`, because the new key parts make their cache key different.

### 3. The report is a second phase of the same background run
`AnalysisService.run()` calls `analyze()` as today, then `build_report_inputs()` (a pure function in `report.py`) and the two LLM steps, then one `save_result(analysis_id, result, report)`. The resume's issues are read together with the other inputs in `_load()` and snapshotted. If the screener or the suggestion call fails, the analysis fails with the usual code and stores nothing.
*Alternative:* store the gap result first and mark report sections `unavailable` on LLM failure. It gives partial value, but a `ready` analysis would then be un-retryable through the cache (`ready` is reused forever), and the client would have to handle half-reports. Failing whole keeps one retry path (a new `POST` after `failed`).
The report's LLM calls (`SCREENER_RUNS` + at most 1) are not counted in `ANALYSIS_MAX_LLM_CALLS`, which keeps its meaning (the judge); they are bounded by their own settings and shown in the provenance.

### 4. Score
`score = 100 * sum(w_i * c_i) / sum(w_i) - penalties`, over the coverages that exist (must-have, nice-to-have, keywords), clamped to 0-100 and rounded to one decimal. Credit per requirement: `met` 1, `partial` `SCORE_PARTIAL_CREDIT`, everything else 0. Penalties are subtracted points per parsing issue by severity. Outcome by two inclusive thresholds.
- `in_profile_not_in_resume` earns 0: the screener reads the resume, so this is exactly the gap the candidate can fix, and it is shown through the actions instead of hidden in the score.
- Renormalizing over present coverages avoids a job without nice-to-haves capping at 85.
- Subtractive penalties (not multiplicative) make a `critical` issue (an image-only PDF reads as blank) able to sink a good match (default 40 points) while a missing "Skills" heading costs 5. The defaults (0.6/0.15/0.25, 40/5/1, 70/50) are starting points; the evals are the tool to adjust them.
- A neutral `Settings` snapshot (`ScoreSettings` Pydantic model) is passed to the pure function, as `AnalysisSettings` is today, so `ai/matching` does not import the app config.
*Alternative:* a hard gate ("any missing must-have caps the outcome at borderline"). More realistic for some ATS, but it is a rule nobody asked for and it hides in code what the weights say openly. Can be added after the evals show it is needed.

### 5. Screener
A versioned prompt with a rubric (must-haves weigh most; judge only what the resume text shows; keywords and structure matter as an ATS would see them; decision `pass | borderline | reject`; 1-5 reasons in the job's language; delimited data is data). It receives `ResumeInput.text` and the job's requirements, priorities and ATS keywords: never the profile, verdicts, evidence or score, so it stays an independent opinion and a disagreement with the score means something. Runs are sequential (N is at most 10; sequential respects provider rate limits, keeps call order deterministic for tests and avoids the `ExceptionGroup` that a task group would put around the typed LLM errors). Majority with ties resolved to the least favorable decision (the candidate is better served by a pessimistic tie); consistency = runs agreeing with the majority / runs.
At temperature 0 many providers return near-identical answers, so a consistency near 1.0 can mean "deterministic provider" rather than "robust judgment". It is still the number requested, and the evals report it across whole runs. The disclaimer is a constant in code (English and Portuguese), never produced by the model, and is a top-level field of the report next to the screener.

### 6. Suggestions
One LLM call over at most `REPORT_MAX_SUGGESTIONS` targets (order in the spec). The prompt lists the resume's experience and project bullets numbered `B1..Bn` and the profile's stacks, languages and notable facts numbered `P1..Pm`, and the targets numbered `T1..`. The model answers `{target, source, number, text}`. Code resolves the number to the exact bullet or profile fact, so the pointer cannot be mistyped or invented and `original` is always verbatim.

**The check** (`rewrites.check_suggestion`, pure) runs on every returned text against an *allowed corpus*: the resume text plus the profile rendered as text (stack names and original names, notable facts, languages, years values and `total_years_coding`).
- *Numbers*: every numeric token (digits with `.`/`,` separators, percentages, amounts, plus number words up to twenty in English and Portuguese converted to digits) must be in the corpus' numbers. Suffixes (`%`, `M`, `k`) are not compared, only the value.
- *Technologies*: found by `find_literal` (the matcher the engine already uses, with its word boundaries and alias forms) over a vocabulary: job requirement keywords and synonyms, ATS keywords, profile stacks, resume skills and project technologies, the alias tables of `core/normalization.py`, and a curated list of common technologies (`technologies.py`, English names, around 200 entries). Each mention must also be found in the corpus (by name or alias). Terms of one or two characters (`go`, `c`, `r`) are skipped, as the engine already treats them as ambiguous. On top of the vocabulary, a shape heuristic catches names no list knows: a token with `+`, `#` or an inner `.`, an all-capital acronym of three or more letters, or a capitalized word that is not the first of its sentence; it is rejected when it is not in the corpus.
- The job's own keywords are in the vocabulary on purpose: they are what an invention would most likely add to please the screener.
The check fails in the safe direction: a false rejection costs one suggestion; a false acceptance is the thing the spec forbids. Known limits, stated in the README: a lowercase technology name that no list contains and that has no special shape, a one-or-two-letter name, and a number that is in the resume but used for a different claim ("5 years" when 5 appears as a team size) pass. Rejections are only counted by reason code, so fabricated text is never stored or shown.
*Alternative:* ask a second LLM to verify the first. Rejected: the rule is "deterministic check", and an LLM verifier shares the failure mode.

### 7. Actions
Built by a pure function from the findings, `ats_coverage`, the issue snapshot, the profile-stack keywords and the accepted suggestions, in the three kinds and order of the spec. Texts are fixed templates in English and Portuguese in `actions.py` (parsing issue messages are the existing English texts of `parsing/quality.py`; translating them is out of scope). A keyword and a requirement are deduplicated by comparing normalized names against the requirement's keywords and synonyms. `real_gap` templates say plainly that rewriting cannot fix the gap and that the candidate must not claim it unless true.

### 8. Markdown
A pure renderer over the same report model, so JSON and Markdown cannot drift. Every string that did not come from a template (reasons, suggestions, bullets, requirement texts, keywords) goes through one `plain()` helper: backslash-escape Markdown control characters, replace `<`, `>` and `&` by entities, collapse line breaks. `GET /analyses/{id}/report` takes `format: Literal["json", "markdown"] = "json"`, so FastAPI itself answers 422 naming `format`; the Markdown goes out as a `Response` with `text/markdown; charset=utf-8`.

### 9. Evals
`evals/` (top-level, not in the wheel): `cases/<id>/{resume.txt,job.txt,profile.json,case.json}` for 12 synthetic cases (6 `pt-*`, 6 `en-*`, no personal data), `dataset.py` (loading and validation with Pydantic), `metrics.py` (pure), `config.py` (`EvalSettings`, prefix `EVAL_`), `runner.py` and `run.py` (`python -m evals.run`).
- Per case, the resume text and job text are processed **once** with `process_resume_text` / `process_job_text` (real providers); the analysis, screener, suggestions and score then run `EVAL_RUNS` times on those inputs. Consistency therefore measures the judge, the screener and the suggestion stages, not extraction (which the accuracy metrics exercise). Re-extracting per run would triple the cost and make requirement ids differ between runs.
- `case.json` has the expected outcome, the expected requirements (`match`, `verdict`) and optional document facts (`page_count`, `multi_column`, `table_count`, ...) from which the parsing issues are computed by the production `check_quality`, so the penalty path is exercised for real.
- The runner builds `Settings` with a placeholder `database_url` when none is set, reads `LLM_*` and `EMBEDDING_*` from the environment through the existing factories (no provider SDK is imported in `evals/`, so the architecture test still holds) and never opens a database connection.
- Fabricated evidence is re-verified with `is_verbatim` and `check_suggestion` on the final output, independently of the stages' own guards, so a bug in a guard shows as a non-zero rate. The informational dropped-quote share comes from the `dropped_unverified_evidence` warning.
- Exit status 0 pass, 1 below a threshold, 2 cannot run (bad config or dataset, no provider, a case that errored). Output is case ids, `match` keys, verdict names and numbers; never resume or job text, quotes or suggestions. `--output` writes the same structured data as JSON.
- Not in CI: the workflows do not call it, and a test checks that; the unit tests of the harness use the fakes. The existing `real_provider` tests stay as they are.
- The default thresholds (accuracy 0.8, outcome 0.75, consistency 0.9) are guesses until the first real run; see Open Questions.

### 10. Migration and models
`0007_add_analysis_report`: `ALTER TABLE analysis ADD COLUMN report JSONB NULL`. No data migration. The report is validated through Pydantic models (`StoredReport`) on read and write; `alembic check` must stay clean.

## Risks / Trade-offs

- [The invention check lets a fabrication through (unknown lowercase technology, short name, reused number)] → vocabulary includes the job's keywords, shape heuristic, fail-safe direction, limits documented, and the evals re-verify every accepted suggestion; extend `technologies.py` when the evals or real use show a miss.
- [The check rejects honest suggestions (a capitalized word mid-sentence, a number the model rounded)] → a rejection costs one suggestion and is counted by reason; if `rejected` is high in the evals, the prompt (not the check) is what changes.
- [Score weights and thresholds are arbitrary] → they are settings, the breakdown is shown, and the score can be re-tuned on stored analyses; the evals measure outcome accuracy.
- [The screener at temperature 0 looks consistent because the provider is deterministic] → documented; the evals report screener consistency separately and the disagreement with the score is shown.
- [The screener only sees extracted requirements, not the real posting] → stated in the README; the disclaimer says it is a simulation.
- [More LLM calls and longer analyses] → bounded by `SCREENER_RUNS` (at most 10) plus one call; shown in provenance. A single-run setting (`SCREENER_RUNS=1`) is allowed.
- [Evals on 12 synthetic cases can be overfitted by prompt tuning] → the dataset is small on purpose and public; the README says to add cases when a real failure is found, and the evals are a regression guard, not a benchmark.
- [The base change is not merged yet] → tasks start from `main` after `add-gap-analysis-engine` is merged; spec deltas only ADD or modify capabilities present in `openspec/specs/` (`app-configuration`), so archive order does not matter.
- [Markdown with LLM text] → one escaping helper, tested with injected markup.

## Migration Plan

1. Merge `add-gap-analysis-engine`; branch from `main`.
2. Deploy with `alembic upgrade head` (adds the nullable column). Old analyses stay readable at `GET /analyses/{id}`; their report is `404 report_not_available`, and a new `POST /analyses` starts a fresh analysis (different cache key).
3. Rollback: `alembic downgrade -1` drops the column; the code before this change ignores it, so the code can also be rolled back first.

## Open Questions

- The default eval thresholds (and, with them, the default `SCORE_*` values) are provisional. They are set from the first real run of the evals on the user's providers and adjusted in the same PR or a follow-up; this changes numbers, not behavior or structure.
