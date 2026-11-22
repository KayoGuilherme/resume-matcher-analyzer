# Spec Delta

## Purpose

Turns a finished analysis into the answer the candidate needs: whether a first-step screener would probably let the resume through and what to do about it, in priority order, readable as JSON by programs and as Markdown by people.

## ADDED Requirements

### Requirement: The report can be read as JSON or Markdown
The system SHALL expose `GET /analyses/{id}/report`. With no `format`, or `format=json`, the response MUST be HTTP 200 with `application/json`. With `format=markdown` it MUST be HTTP 200 with `text/markdown; charset=utf-8`. Any other `format` MUST give 422 and the message MUST name the parameter. An unknown analysis MUST give 404 with code `analysis_not_found`; an analysis that is `processing` MUST give 409 with code `report_not_ready`; a `failed` analysis MUST give 409 with code `analysis_failed` (its error is read with `GET /analyses/{id}`); a `ready` analysis that has no stored report (it was made before reports existed) MUST give 404 with code `report_not_available`. Reading the report MUST NOT call an LLM, an embedding provider or any other analysis step.

#### Scenario: JSON by default
- **WHEN** a client reads the report of a `ready` analysis without `format`
- **THEN** the response is 200 with a JSON body

#### Scenario: Markdown
- **WHEN** a client reads it with `?format=markdown`
- **THEN** the response is 200 with content type `text/markdown; charset=utf-8`

#### Scenario: Unknown format
- **WHEN** the client uses `?format=pdf`
- **THEN** the response is 422 and the message names `format`

#### Scenario: Analysis not found
- **WHEN** the id does not exist
- **THEN** the response is 404 with code `analysis_not_found`

#### Scenario: Still running
- **WHEN** the analysis is `processing`
- **THEN** the response is 409 with code `report_not_ready`

#### Scenario: Failed analysis
- **WHEN** the analysis is `failed`
- **THEN** the response is 409 with code `analysis_failed`

#### Scenario: Analysis without a report
- **WHEN** the analysis is `ready` and holds no report
- **THEN** the response is 404 with code `report_not_available`

#### Scenario: No provider is called
- **WHEN** the report is read with no LLM or embedding provider configured
- **THEN** the response is the same as with one configured and no provider is called

### Requirement: The JSON report holds everything the candidate needs
The JSON report MUST contain: the ids of the analysis, the resume and the job; the job's language; the disclaimer (see "Every report carries the disclaimer"); the score with its breakdown and outcome (see "The score is a weighted coverage minus parsing penalties"); the screener's decision, consistency, agreement with the score and every run (see "The screener runs several times and the report says how much the runs agree"); the ATS keyword coverage (found with the matched text, and missing); the prioritized actions; the accepted rewrite suggestions; warnings (counts by code, including rejected suggestions by reason); and the provenance (prompt names and versions, LLM provider and model, number of LLM calls of the report, the number of screener runs and the settings that shaped the score).

#### Scenario: Complete report
- **WHEN** the report of a `ready` analysis is read as JSON
- **THEN** it has the disclaimer, the score, the screener, the keyword coverage, the actions, the suggestions, the warnings and the provenance

#### Scenario: Provenance
- **WHEN** the report is read
- **THEN** the provenance names the screener and suggestion prompts with their versions and the LLM used

### Requirement: Actions are prioritized in three kinds
The report MUST list actions in this order of kinds, with a contiguous `priority` number starting at 1 that follows the list order:
1. `fix_format`: one per parsing issue of the resume, most severe first (`critical`, `warning`, `info`, then by code), with the issue's code, severity and message.
2. `add_from_profile`: one per requirement whose verdict is `in_profile_not_in_resume`, and one per missing ATS keyword that is the name of a stack in the candidate profile and does not belong to such a requirement, `must_have` before `nice_to_have`, keeping the job's order, each listing the ids of the accepted suggestions that address it. The action MUST say that the candidate's profile shows it and the resume does not, and what to add.
3. `real_gap`: one per requirement whose verdict is `missing` or `partial` (these are not backed by the profile either), `must_have` before `nice_to_have`, and one per missing ATS keyword that is not in the profile and does not belong to a requirement that already has an action. The action MUST say honestly that rewriting cannot fix it and that it must not be added to the resume unless it is true, and that it is a real gap in skills, experience or evidence.

Action texts MUST come from fixed templates in the language of the job (English when it is not Portuguese), not from an LLM. A requirement MUST NOT appear in two actions. An action about a requirement MUST carry its id, text and priority (`must_have` or `nice_to_have`).

#### Scenario: Order of kinds
- **WHEN** the resume has two parsing issues, a requirement `in_profile_not_in_resume` and a `missing` must-have
- **THEN** the actions are the two format fixes, then the profile action, then the real gap, with priorities 1, 2, 3 and 4

#### Scenario: Severity first
- **WHEN** the issues are a `warning`, a `critical` and an `info`
- **THEN** the format fixes are ordered `critical`, `warning`, `info`

#### Scenario: Must before nice
- **WHEN** a nice-to-have and a must-have are both `missing`
- **THEN** the must-have's real-gap action comes first

#### Scenario: Honest about real gaps
- **WHEN** a requirement is `missing` and the profile does not show it
- **THEN** its action is a `real_gap` that says that rewriting cannot fix it and that it must not be claimed unless true

#### Scenario: Profile action links its suggestions
- **WHEN** a requirement is `in_profile_not_in_resume` and one suggestion was accepted for it
- **THEN** its `add_from_profile` action lists that suggestion's id

#### Scenario: Keyword not in the profile
- **WHEN** an ATS keyword is missing, is not a profile stack and belongs to no requirement that has an action
- **THEN** it has a `real_gap` action naming the keyword

#### Scenario: No duplicate
- **WHEN** a missing ATS keyword is a keyword of a `missing` requirement
- **THEN** only the requirement has an action

#### Scenario: Portuguese job
- **WHEN** the job is in Portuguese
- **THEN** the action texts are in Portuguese

#### Scenario: Nothing to do
- **WHEN** the resume has no parsing issue and every requirement is `met` and every keyword is found
- **THEN** the list of actions is empty

### Requirement: The Markdown report mirrors the JSON report and is safe to render
The Markdown report MUST present, in this order: a title, the disclaimer, the score with its outcome and breakdown, the screener's decision with its consistency and reasons, the actions by kind, the accepted rewrite suggestions (original and suggested text), the ATS keyword coverage and the warnings. It MUST hold the same facts as the JSON report. Any text that came from an LLM or from the resume or the job (reasons, suggested text, original bullets, requirement texts, keywords) MUST be inserted as plain text: Markdown and HTML control characters escaped and line breaks collapsed, so that such text cannot add headings, links, images or HTML to the document.

#### Scenario: Sections in order
- **WHEN** the report is read as Markdown
- **THEN** the disclaimer comes before the score, the score before the screener, the screener before the actions and the actions before the suggestions

#### Scenario: Same facts
- **WHEN** the report is read as JSON and as Markdown
- **THEN** the score, the outcome, the screener's decision and consistency and the number of actions are the same in both

#### Scenario: Injected markup
- **WHEN** a screener reason is "# Pwned [click](http://x.example) <script>alert(1)</script>"
- **THEN** the Markdown shows it as text and contains no heading, link or tag created by it

### Requirement: The report is produced by the analysis run and stored with it
After the gap analysis finishes, the same background run MUST run the screener and the suggestions and MUST store, together with the result, a report holding them, the job's language, the missing ATS keywords (each with whether the candidate profile has it as a stack and which requirements it belongs to) and a snapshot of the resume's parsing issues, in one write. The analysis MUST become `ready` only when its result and report are stored. A failure of the screener or of the suggestions (an unusable LLM, an answer that stays invalid) MUST end the analysis as `failed` with the same stable codes and safe messages as the gap analysis, and nothing of the result or report MUST be stored. The LLM calls of the report (the screener runs and at most one suggestion call) MUST be counted apart from `ANALYSIS_MAX_LLM_CALLS`. The analysis cache key MUST also include the screener prompt and its version, the suggestion prompt and its version, `SCREENER_RUNS` and `REPORT_MAX_SUGGESTIONS`, so that a change to any of them starts a new analysis instead of returning a report made with the old ones. It MUST NOT include the `SCORE_*` settings.

#### Scenario: Ready means a report exists
- **WHEN** an analysis is `ready`
- **THEN** its report can be read

#### Scenario: Screener failure
- **WHEN** the LLM is unavailable during the screener runs
- **THEN** the analysis is `failed` with code `llm_unavailable`, no result and no report are stored, and a new request starts a new run

#### Scenario: Calls of the report
- **WHEN** an analysis needs 3 judge calls, `SCREENER_RUNS` is 3 and one suggestion call is made
- **THEN** the report's provenance counts 4 LLM calls for the report and the limit `ANALYSIS_MAX_LLM_CALLS` is applied to the 3 judge calls only

#### Scenario: Cache after a change
- **WHEN** an analysis is `ready` and `SCREENER_RUNS` changes from 3 to 5
- **THEN** a new request for the same resume and job starts a new analysis

#### Scenario: Cache after a score change
- **WHEN** an analysis is `ready` and `SCORE_PASS_THRESHOLD` changes
- **THEN** a new request for the same resume and job returns the same stored analysis without LLM calls

#### Scenario: Stored with the analysis
- **WHEN** the resume or the job is deleted
- **THEN** its analyses and their reports are deleted

### Requirement: The score follows the settings in force when the report is read
The score, the outcome, the actions and the Markdown MUST be computed when the report is read, from the stored result and report and the current `SCORE_*` settings, so that changing them changes the reports of existing analyses without any LLM call. The report MUST state the weights, penalties and thresholds it used.

#### Scenario: Threshold change
- **WHEN** an analysis scored 67.5 is read with a pass threshold of 70 and then again with 65
- **THEN** the outcome is `borderline` and then `likely_pass`, with the same screener result

#### Scenario: Settings stated
- **WHEN** the report is read
- **THEN** it states the weights, penalties and thresholds used for the score

### Requirement: The report stays out of logs
The system MUST NOT log the content of a report (reasons, suggestions, requirement texts, keywords or bullets). It MAY log the analysis id, counts, codes and durations.

#### Scenario: Logs after reading a report
- **WHEN** a report is read
- **THEN** no log record contains report content
