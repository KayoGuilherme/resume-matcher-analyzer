# Spec Delta

## Purpose

Measures, on a fixed set of synthetic Portuguese and English cases, whether the real pipeline gets requirement verdicts and outcomes right, never invents evidence and answers consistently, and fails loudly when a metric drops below its threshold, so that prompt, model and threshold changes are judged by numbers.

## ADDED Requirements

### Requirement: A dataset of synthetic cases with expected results
The repository SHALL contain, under `evals/`, between 10 and 15 cases (12 are delivered), at least 5 in Portuguese and at least 5 in English. Each case MUST hold a resume as text, a job posting as text, a candidate profile, optional document facts (page count, multi-column layout, table count, image count, header or footer text) from which the resume's parsing issues are computed with the same checks used when a resume is uploaded, the expected outcome (`likely_pass`, `borderline` or `likely_reject`) and a list of expected requirements. An expected requirement MUST have a `match` text and an expected verdict (`met`, `partial`, `missing` or `in_profile_not_in_resume`); it is matched to the job's extracted requirements by comparing the folded `match` text (lowercase, no accents) with the folded requirement text and its keywords, and it MUST match exactly one requirement. Across the dataset every one of the three outcomes MUST appear at least 3 times, every one of the four verdicts MUST be expected at least 3 times, and the resumes of at least 2 cases MUST yield at least one parsing issue. The cases MUST be synthetic: no real person, employer or contact data, and no e-mail address, phone number or URL in any case file.

#### Scenario: Size and languages
- **WHEN** the dataset is loaded
- **THEN** it has 10 to 15 cases, at least 5 Portuguese and at least 5 English

#### Scenario: Coverage of outcomes and verdicts
- **WHEN** the dataset is loaded
- **THEN** each outcome appears in at least 3 cases and each verdict is expected at least 3 times

#### Scenario: Invalid case
- **WHEN** a case has an unknown verdict, an unknown outcome, a missing file or an expected `match` that is empty
- **THEN** loading fails with an error that names the case and the problem, and nothing is run

#### Scenario: No personal data
- **WHEN** the case files are scanned
- **THEN** none contains an e-mail address, a phone number or a URL

### Requirement: The runner executes the real pipeline for every case
The system SHALL provide `uv run python -m evals.run`. For every case the runner MUST process the resume text and the job text with the configured LLM and embedding providers, build the analysis input with the case's profile, run the gap analysis, the screener, the suggestions and the score exactly as the analysis run does, and repeat this for `EVAL_RUNS` runs (default 3, whole number from 1 to 10; `--runs N` overrides it). `--case ID` (repeatable) MUST limit the run to those cases. The runner MUST NOT connect to the database, MUST NOT write any file unless `--output PATH` is given, and MUST NOT print resume, job or profile text, evidence quotes or suggestion texts.

#### Scenario: Full run
- **WHEN** the runner is started with the providers configured
- **THEN** every case is processed `EVAL_RUNS` times and a summary is printed

#### Scenario: Selected cases
- **WHEN** it is started with `--case en-01 --case pt-02`
- **THEN** only those two cases are run

#### Scenario: Unknown case id
- **WHEN** it is started with `--case nope`
- **THEN** it ends with exit status 2 and a message that names the unknown id, and nothing is run

#### Scenario: No provider configured
- **WHEN** it is started with no LLM provider configured
- **THEN** it ends with exit status 2 and a message that says which settings to provide, without a stack trace

#### Scenario: No database
- **WHEN** it is started without `DATABASE_URL`
- **THEN** it still runs and never opens a database connection

#### Scenario: Output file
- **WHEN** it is started with `--output results.json`
- **THEN** the full per-case results are written to that file, and nothing is written when the option is absent

### Requirement: Four metrics are reported
The runner MUST report, over all cases and runs:
- **Requirement-verdict accuracy**: the share of expected requirements whose actual verdict equals the expected one. An expected requirement that matched no requirement, or more than one, counts as wrong and is listed.
- **Outcome accuracy**: the share of case runs whose score outcome equals the expected outcome.
- **Fabricated-evidence rate**: the number of evidence quotes of source `resume` that are not found in the resume text, plus the number of suggestions that fail the invention check, divided by the number of quotes and suggestions. Both MUST be re-verified by the runner with the same deterministic functions used in production but independently of the stage that produced them. It MUST be reported together with the share of quotes the judge gave that the guard dropped (informational).
- **Consistency**: for each expected requirement, the share of the runs that gave its most frequent verdict, averaged over all expected requirements. The runner MUST also report the screener's mean consistency and the share of runs that gave each case's most frequent outcome (both informational).

The report MUST also list, per case, the expected and actual outcome and the requirements whose verdict was wrong, by their `match` text, expected verdict and actual verdict.

#### Scenario: Accuracy
- **WHEN** 20 expected requirements are checked and 17 have the expected verdict
- **THEN** the requirement-verdict accuracy is 0.85

#### Scenario: Unmatched expectation
- **WHEN** an expected `match` text is in no extracted requirement
- **THEN** it counts as wrong and is listed with the reason "no requirement matched"

#### Scenario: Ambiguous expectation
- **WHEN** an expected `match` text is in two extracted requirements
- **THEN** it counts as wrong and is listed with the reason "more than one requirement matched"

#### Scenario: Fabricated evidence
- **WHEN** a finding holds a resume quote that is not in the resume text
- **THEN** the fabricated-evidence rate is above 0, even though the pipeline's own guard should have dropped it

#### Scenario: Consistency
- **WHEN** over 3 runs a requirement's verdicts are `met`, `met`, `partial`
- **THEN** it contributes a consistency of 0.67

#### Scenario: Per-case report
- **WHEN** the run finishes
- **THEN** each case is listed with its expected and actual outcome and its wrong requirements, without any resume or job text

### Requirement: The runner fails when a metric is below its threshold
The runner MUST compare the metrics with their thresholds and end with exit status 0 only when all pass. The thresholds are `EVAL_MIN_VERDICT_ACCURACY` (default 0.8), `EVAL_MIN_OUTCOME_ACCURACY` (default 0.75) and `EVAL_MIN_CONSISTENCY` (default 0.9), each a number from 0 to 1 read from the environment, and the fabricated-evidence rate, whose threshold is fixed at 0 and cannot be configured: any fabricated evidence MUST fail the run. When a threshold is not met the runner MUST end with exit status 1 and print which metrics failed, with their value and threshold. A case that cannot finish (the provider failed after its retries, for example) MUST be reported as an error and the run MUST end with exit status 2, because metrics over a partial run are not trusted. An invalid threshold MUST end the run with exit status 2 and a message that names the setting.

#### Scenario: All pass
- **WHEN** the verdict accuracy is 0.85, the outcome accuracy 0.8, the consistency 0.95 and no evidence is fabricated
- **THEN** the exit status is 0

#### Scenario: Below a threshold
- **WHEN** the verdict accuracy is 0.7 and its threshold is 0.8
- **THEN** the exit status is 1 and the output names `verdict accuracy`, 0.7 and 0.8

#### Scenario: Any fabricated evidence
- **WHEN** the fabricated-evidence rate is greater than 0 and all other metrics pass
- **THEN** the exit status is 1

#### Scenario: A case fails to finish
- **WHEN** the LLM is unavailable for one case
- **THEN** that case is listed as an error and the exit status is 2

#### Scenario: Invalid threshold
- **WHEN** `EVAL_MIN_CONSISTENCY=1.5`
- **THEN** the exit status is 2 and the message names `EVAL_MIN_CONSISTENCY`

### Requirement: The evals run locally and are documented
The evals MUST NOT run in continuous integration or in the default `uv run pytest` run, and the unit tests of the harness (dataset validation, matching of expectations, metrics, thresholds and exit status) MUST use fakes and make no network call. The README MUST document how to run the evals, the environment they need, that they spend tokens and send the synthetic cases to the configured provider, how to read the output and the exit statuses, how to add a case, and that the default thresholds are a starting point to tune. `.env.example` MUST list `EVAL_RUNS`, `EVAL_MIN_VERDICT_ACCURACY`, `EVAL_MIN_OUTCOME_ACCURACY` and `EVAL_MIN_CONSISTENCY` with their defaults.

#### Scenario: Not in CI
- **WHEN** the workflow files are read
- **THEN** none of them runs `evals.run`

#### Scenario: Default test run
- **WHEN** `uv run pytest` is run
- **THEN** no provider is called and no eval case is run against a real provider

#### Scenario: Documented
- **WHEN** the README is read
- **THEN** it shows the command, the settings, the metrics, the exit statuses and how to add a case

#### Scenario: Example file
- **WHEN** `.env.example` is read
- **THEN** it lists the four `EVAL_*` settings
