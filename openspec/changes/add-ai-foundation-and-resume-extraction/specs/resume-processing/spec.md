# Spec Delta

## Purpose

Lets the candidate start and follow the processing of a stored resume into structured data and vectors, with an explicit status and safe failure reporting, running in the background so the request returns immediately.

## ADDED Requirements

### Requirement: A resume has a processing status
Every resume SHALL have a status: `uploaded` (stored, not processed), `processing`, `ready` (processed successfully) or `failed`. A newly uploaded resume is `uploaded`. When the status is `failed`, the resume MUST also expose an error with a stable `code` and a short `message` that never contains resume text. The status and the error are part of the resume representation.

#### Scenario: New resume
- **WHEN** a resume is uploaded
- **THEN** its status is `uploaded` and it has no error

#### Scenario: Failed resume
- **WHEN** processing failed
- **THEN** the status is `failed` and the error has a code and a message

### Requirement: Processing is started with a request and runs in the background
The system SHALL expose `POST /resumes/{id}/process`. For a resume that can be processed it MUST set the status to `processing`, return HTTP 202 with the resume (status `processing`) without waiting for the work, and then run extraction, chunking and embedding in the background. An unknown `id` MUST give 404 with code `resume_not_found`. A resume that is already `processing` MUST give 409 with code `already_processing` and start nothing. A resume that is `uploaded`, `ready` or `failed` can be processed (again).

#### Scenario: Start
- **WHEN** a client sends `POST /resumes/{id}/process` for an uploaded resume
- **THEN** the response is 202 with status `processing`

#### Scenario: Result is observable
- **WHEN** the background work succeeds and the client reads `GET /resumes/{id}`
- **THEN** the status is `ready` and the extraction is present

#### Scenario: Already running
- **WHEN** processing is requested for a resume that is `processing`
- **THEN** the response is 409 with code `already_processing`

#### Scenario: Two simultaneous requests
- **WHEN** two process requests for the same resume arrive at the same time
- **THEN** exactly one starts the work and the other gets 409

#### Scenario: Unknown resume
- **WHEN** the id does not exist
- **THEN** the response is 404 with code `resume_not_found`

#### Scenario: Process again
- **WHEN** a `ready` or `failed` resume is processed again
- **THEN** it becomes `processing` and, on success, `ready` with a new extraction and new chunks

### Requirement: AI configuration problems are reported before work starts
When the LLM or the embeddings are not usable, `POST /resumes/{id}/process` MUST answer 503 with code `ai_not_configured` and MUST NOT change the resume's status.

#### Scenario: Not configured
- **WHEN** no LLM is configured and processing is requested for an uploaded resume
- **THEN** the response is 503 with code `ai_not_configured` and the resume stays `uploaded`

### Requirement: Successful processing stores extraction and chunks
When extraction, chunking and embedding succeed, the system MUST store the extraction and the chunks and set the status to `ready` in one step, and clear any previous error. The stored extraction MUST be returned by `GET /resumes/{id}`.

#### Scenario: Ready
- **WHEN** processing succeeds
- **THEN** the status is `ready`, the error is empty, the extraction is present and the chunks exist

### Requirement: Failures end as `failed` with a safe error
When processing fails, the status MUST become `failed` with one of these error codes and a message without resume content: `llm_auth_failed`, `llm_timeout`, `llm_unavailable` (transient errors after the retries), `llm_invalid_output`, `embedding_failed` (including dimension mismatch and unavailable provider), `processing_interrupted` and `processing_failed` (any other error). A failed run MUST NOT replace the previous extraction and chunks of a resume that was processed before.

#### Scenario: Invalid LLM output
- **WHEN** the LLM output cannot be validated after the repair attempt
- **THEN** the status is `failed` with code `llm_invalid_output`

#### Scenario: Authentication
- **WHEN** the provider rejects the credentials
- **THEN** the status is `failed` with code `llm_auth_failed` and the message does not contain the key

#### Scenario: Unexpected error
- **WHEN** an unexpected exception occurs while processing
- **THEN** the status is `failed` with code `processing_failed` and no exception text is stored or logged beyond its type

#### Scenario: Previous results survive
- **WHEN** a `ready` resume is processed again and the run fails
- **THEN** its previous extraction and chunks are still present, and its status is `failed`

### Requirement: Interrupted processing does not stay stuck
When the application starts, every resume that is still `processing` (its background work died with the previous process) MUST be set to `failed` with code `processing_interrupted`, so it can be processed again.

#### Scenario: Restart during processing
- **WHEN** the application restarts while a resume is `processing`
- **THEN** after startup the resume is `failed` with code `processing_interrupted`

### Requirement: Processing logs contain no content
Processing SHALL log the resume id, status transitions, counts of items kept, dropped and chunked, and durations, and MUST NOT log resume text, extracted text, prompts or vectors.

#### Scenario: Log content
- **WHEN** a resume is processed successfully and unsuccessfully
- **THEN** no log entry contains text from the resume
