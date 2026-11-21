# Spec Delta

## Purpose

Lets the candidate ask for the comparison of one stored resume with one stored job position, follow its progress and read its result, with explicit preconditions, a status and safe failure reporting, repeated requests that do not spend tokens again, and a bounded use of the LLM.

## ADDED Requirements

### Requirement: An analysis can be requested
The system SHALL expose `POST /analyses` with a JSON body holding `resume_id` and `job_id` (both UUIDs; unknown fields MUST be rejected with 422). When a new analysis starts, the response MUST be HTTP 202 with the analysis (status `processing`, see "An analysis can be read") and the work MUST run in the background, after the response. An unknown resume MUST give 404 with code `resume_not_found` and an unknown job 404 with code `job_not_found`. The request MUST NOT change the resume, the job or the profile.

#### Scenario: Start
- **WHEN** a client sends `POST /analyses` for a ready resume and a ready job and a profile exists
- **THEN** the response is 202 with status `processing`, `resume_id` and `job_id`

#### Scenario: Result is observable
- **WHEN** the background work succeeds and the client reads `GET /analyses/{id}`
- **THEN** the status is `ready` and the result is present

#### Scenario: Unknown resume
- **WHEN** the `resume_id` does not exist
- **THEN** the response is 404 with code `resume_not_found` and no analysis is stored

#### Scenario: Unknown job
- **WHEN** the `job_id` does not exist
- **THEN** the response is 404 with code `job_not_found` and no analysis is stored

#### Scenario: Invalid body
- **WHEN** the body has no `job_id`, a `resume_id` that is not a UUID, or a field that is not defined
- **THEN** the response is 422 and the message names the field

### Requirement: Preconditions are checked before anything is stored or spent
An analysis MUST only start when the resume has status `ready`, the job has status `ready`, the candidate profile exists, and the resume's chunks and the job's requirements were embedded with the same embedding model. Otherwise the response MUST be HTTP 409 with code `resume_not_ready`, `job_not_ready`, `profile_required` or `embedding_model_mismatch` (checked in that order, the first that fails is reported), with a message that says what to do (process the resume or the job, save the profile, or process the older of the two again), and nothing MUST be stored. When the LLM is not usable, the response MUST be 503 with code `ai_not_configured` and nothing MUST be stored; this is answered before any of the checks above.

#### Scenario: Resume not ready
- **WHEN** the resume is `uploaded`, `processing` or `failed`
- **THEN** the response is 409 with code `resume_not_ready` and no analysis is stored

#### Scenario: Job not ready
- **WHEN** the resume is ready and the job is `uploaded`, `processing` or `failed`
- **THEN** the response is 409 with code `job_not_ready`

#### Scenario: No profile
- **WHEN** both are ready and no profile has been saved
- **THEN** the response is 409 with code `profile_required` and the message says to save the profile with `PUT /profile`

#### Scenario: Different embedding models
- **WHEN** the resume's chunks and the job's requirements were embedded with different embedding models
- **THEN** the response is 409 with code `embedding_model_mismatch` and the message says to process the older one again

#### Scenario: LLM not configured
- **WHEN** no LLM provider is configured
- **THEN** the response is 503 with code `ai_not_configured` and no analysis is stored

### Requirement: An analysis can be read
The system SHALL expose `GET /analyses/{id}` returning the analysis: `id`, `resume_id`, `job_id`, `status` (`processing`, `ready` or `failed`), `error` (a stable `code` and a short `message`, only when `failed`), `created_at`, `completed_at` (when finished) and `result` (only when `ready`, see the `requirement-matching` and `ats-keyword-coverage` capabilities). An unknown `id` MUST give 404 with code `analysis_not_found`. The same representation is returned by `POST /analyses`.

#### Scenario: Processing
- **WHEN** the analysis is still running
- **THEN** the response is 200 with status `processing`, no error and no result

#### Scenario: Ready
- **WHEN** the analysis finished
- **THEN** the response is 200 with status `ready`, a `completed_at` and a result

#### Scenario: Failed
- **WHEN** the analysis failed
- **THEN** the response is 200 with status `failed`, an error with a code and a message, and no result

#### Scenario: Unknown analysis
- **WHEN** the id does not exist
- **THEN** the response is 404 with code `analysis_not_found`

### Requirement: Repeated requests reuse the existing analysis
The system SHALL identify an analysis by its inputs: the resume and the job (and their stored processing results), the candidate profile, the version of the judge prompt, the LLM provider and model, and the analysis settings. A `POST /analyses` whose inputs equal those of a `ready` analysis MUST return that analysis with HTTP 200 without calling the LLM and without creating a new analysis. When the equal analysis is `processing`, the request MUST return it with HTTP 202 and start nothing. When the only equal analysis is `failed`, a new analysis MUST start. Any change of the inputs MUST lead to a new analysis, so a saved profile change or a resume or job processed again is never answered with an older result. Two simultaneous requests with the same inputs MUST start exactly one analysis.

#### Scenario: Same request again
- **WHEN** a ready analysis exists and the same request is sent again
- **THEN** the response is 200 with the same analysis id, and no LLM call is made

#### Scenario: Same request while running
- **WHEN** an analysis for the same inputs is `processing`
- **THEN** the response is 202 with the same analysis id and nothing new starts

#### Scenario: Profile changed
- **WHEN** a ready analysis exists, the profile is replaced with different content, and the same request is sent
- **THEN** a new analysis starts (202 with a different id) and the old one is kept

#### Scenario: Resume processed again
- **WHEN** the resume is processed again after a ready analysis and the same request is sent
- **THEN** a new analysis starts

#### Scenario: Prompt version changed
- **WHEN** the judge prompt has a new version
- **THEN** the same request starts a new analysis

#### Scenario: Retry after failure
- **WHEN** the only equal analysis is `failed` and the same request is sent
- **THEN** a new analysis starts

#### Scenario: Two simultaneous requests
- **WHEN** two identical requests arrive at the same time and no equal analysis exists
- **THEN** exactly one analysis is created and both responses carry its id

### Requirement: The use of the LLM is limited
The system SHALL send at most `ANALYSIS_MAX_REQUIREMENTS_PER_CALL` requirements in one LLM call and SHALL make at most `ANALYSIS_MAX_LLM_CALLS` LLM calls for one analysis. Only requirements that the earlier steps did not settle are sent. When the calls needed for the requirements that must be judged exceed the maximum, the analysis MUST fail with code `analysis_limit_exceeded` before any LLM call is made, and its message MUST name the two settings. A call that retries unanswered requirements counts as a call and MUST NOT exceed the maximum.

#### Scenario: Batches
- **WHEN** 20 requirements must be judged and at most 8 fit in one call
- **THEN** 3 calls are made, with 8, 8 and 4 requirements

#### Scenario: Nothing to judge
- **WHEN** the earlier steps settle every requirement
- **THEN** no LLM call is made and the analysis is `ready`

#### Scenario: Too many requirements
- **WHEN** 100 requirements must be judged, at most 8 fit in a call and at most 10 calls are allowed
- **THEN** the analysis fails with code `analysis_limit_exceeded` and no LLM call is made

#### Scenario: Retry needs a call that is not left
- **WHEN** the judge left requirements unanswered and the maximum number of calls is already used
- **THEN** the analysis fails with code `llm_invalid_output`

### Requirement: Failures are reported with stable codes and safe messages
When an analysis fails, its `error.code` MUST be one of the processing codes already used for resumes and jobs (`llm_auth_failed`, `llm_timeout`, `llm_unavailable`, `llm_invalid_output`, `processing_failed`, `processing_interrupted`) or one of `analysis_limit_exceeded` and `embedding_model_mismatch`, and `error.message` MUST be a fixed text for that code that never contains resume, job or profile content, evidence or exception text. An analysis that fails MUST NOT have a result.

#### Scenario: Provider unavailable
- **WHEN** the LLM provider keeps answering with server errors
- **THEN** the analysis is `failed` with code `llm_unavailable` and a fixed message

#### Scenario: Unexpected error
- **WHEN** an unexpected exception happens while analyzing
- **THEN** the analysis is `failed` with code `processing_failed` and the message does not contain the exception text

#### Scenario: Embedding model changed while running
- **WHEN** the vectors turn out to come from different embedding models when the analysis runs
- **THEN** the analysis is `failed` with code `embedding_model_mismatch`

### Requirement: Interrupted analyses are recovered at startup
When the application starts, every analysis still `processing` (its background work died with the previous process) MUST be set to `failed` with code `processing_interrupted`. When the database is not reachable the check is skipped with a warning and the application still starts.

#### Scenario: Restart during an analysis
- **WHEN** the application starts and an analysis is `processing`
- **THEN** it becomes `failed` with code `processing_interrupted`

#### Scenario: Database down at startup
- **WHEN** the database is unreachable at startup
- **THEN** the check is skipped with a warning and the application starts

### Requirement: Analyses are stored and deleted with their resume or job
The system SHALL store every analysis, with its status, its inputs' identity and its result, so it survives a restart. Deleting a resume or a job MUST delete the analyses that refer to it. A deleted resume or job while its analysis is running MUST NOT leave the analysis behind or make the application fail.

#### Scenario: Survives a restart
- **WHEN** an analysis is `ready` and the application restarts
- **THEN** `GET /analyses/{id}` still returns the same result

#### Scenario: Resume deleted
- **WHEN** a resume that has analyses is deleted
- **THEN** `GET /analyses/{id}` for each of them answers 404 with code `analysis_not_found`

#### Scenario: Job deleted while running
- **WHEN** the job is deleted while its analysis is `processing`
- **THEN** no analysis for that job remains and the application keeps working

### Requirement: Analysis content stays out of logs
The system MUST NOT write resume text, job text, profile content, requirement texts, evidence quotes or explanations to logs. Logs about an analysis MAY contain ids, counts per verdict and per deciding step, the number of LLM calls, error codes and durations.

#### Scenario: A full analysis
- **WHEN** an analysis runs from start to finish
- **THEN** no log record contains any text from the resume, the job or the profile, or any evidence or explanation
