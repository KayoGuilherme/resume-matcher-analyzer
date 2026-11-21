# Spec Delta

## Purpose

Lets the candidate start and follow the processing of a stored job position into structured requirements and vectors, with the same explicit status and safe failure reporting as resumes, running in the background so the request returns immediately.

## ADDED Requirements

### Requirement: A job has a processing status
Every job SHALL have a status: `uploaded` (stored, not processed), `processing`, `ready` (processed successfully) or `failed`. A newly created job is `uploaded`. When the status is `failed`, the job MUST also expose an error with a stable `code` and a short `message` that never contains posting text. The status and the error are part of the job representation.

#### Scenario: New job
- **WHEN** a job is created
- **THEN** its status is `uploaded` and it has no error

#### Scenario: Failed job
- **WHEN** processing failed
- **THEN** the status is `failed` and the error has a code and a message

### Requirement: Processing is started with a request and runs in the background
The system SHALL expose `POST /jobs/{id}/process`. For a job that can be processed it MUST set the status to `processing`, return HTTP 202 with the job (status `processing`) without waiting for the work, and then run extraction and embedding in the background. An unknown `id` MUST give 404 with code `job_not_found`. A job that is already `processing` MUST give 409 with code `already_processing` and start nothing. A job that is `uploaded`, `ready` or `failed` can be processed (again).

#### Scenario: Start
- **WHEN** a client sends `POST /jobs/{id}/process` for an uploaded job
- **THEN** the response is 202 with status `processing`

#### Scenario: Result is observable
- **WHEN** the background work succeeds and the client reads `GET /jobs/{id}`
- **THEN** the status is `ready` and the extraction is present

#### Scenario: Already running
- **WHEN** processing is requested for a job that is `processing`
- **THEN** the response is 409 with code `already_processing`

#### Scenario: Two simultaneous requests
- **WHEN** two process requests for the same job arrive at the same time
- **THEN** exactly one starts the work and the other gets 409

#### Scenario: Unknown job
- **WHEN** the id does not exist
- **THEN** the response is 404 with code `job_not_found`

#### Scenario: Process again
- **WHEN** a `ready` or `failed` job is processed again
- **THEN** it becomes `processing` and, on success, `ready` with a new extraction and new requirements

### Requirement: AI configuration problems are reported before work starts
When the LLM or the embeddings are not usable, `POST /jobs/{id}/process` MUST answer 503 with code `ai_not_configured` and MUST NOT change the job's status.

#### Scenario: Not configured
- **WHEN** no LLM is configured and processing is requested for an uploaded job
- **THEN** the response is 503 with code `ai_not_configured` and the job stays `uploaded`

### Requirement: Successful processing stores extraction and requirements
When extraction and embedding succeed, the system MUST store the extraction and the requirements and set the status to `ready` in one step, and clear any previous error. The stored extraction MUST be returned by `GET /jobs/{id}`.

#### Scenario: Ready
- **WHEN** processing succeeds
- **THEN** the status is `ready`, the error is empty, the extraction is present and the requirements exist

### Requirement: Failures end as `failed` with a safe error
When processing fails, the status MUST become `failed` with the same error codes and rules as resume processing: `llm_auth_failed`, `llm_timeout`, `llm_unavailable`, `llm_invalid_output`, `embedding_failed`, `processing_interrupted` and `processing_failed`, with messages that never contain posting text. A failed run MUST NOT replace the previous extraction and requirements of a job that was processed before.

#### Scenario: Invalid LLM output
- **WHEN** the LLM output cannot be validated after the repair attempt
- **THEN** the status is `failed` with code `llm_invalid_output`

#### Scenario: Unexpected error
- **WHEN** an unexpected exception occurs while processing
- **THEN** the status is `failed` with code `processing_failed` and no exception text is stored or logged beyond its type

#### Scenario: Previous results survive
- **WHEN** a `ready` job is processed again and the run fails
- **THEN** its previous extraction and requirements are still present, and its status is `failed`

### Requirement: Interrupted processing does not stay stuck
When the application starts, every job that is still `processing` MUST be set to `failed` with code `processing_interrupted`, so it can be processed again.

#### Scenario: Restart during processing
- **WHEN** the application restarts while a job is `processing`
- **THEN** after startup the job is `failed` with code `processing_interrupted`

### Requirement: Jobs and resumes share the processing rules
The status values, error codes, error messages and the `already_processing` error of jobs MUST be the same as those of resumes, defined once and used by both features, so that a change to them applies to both.

#### Scenario: Same codes
- **WHEN** the same failure happens while processing a resume and a job
- **THEN** both end `failed` with the same code and the same message

### Requirement: Processing logs contain no content
Processing SHALL log the job id, status transitions, counts of requirements kept, dropped and flagged, and durations, and MUST NOT log posting text, extracted text, prompts or vectors.

#### Scenario: Log content
- **WHEN** a job is processed successfully and unsuccessfully
- **THEN** no log entry contains text from the posting
