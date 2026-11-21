# Spec Delta

## Purpose

Lets the candidate store the job positions they want to compare their resume against, as free text entered through the API, and list, read and delete them without ever exposing posting content in logs.

## ADDED Requirements

### Requirement: A job position can be created
The system SHALL expose `POST /jobs`, which accepts a JSON body with `title` (required), `company` (optional), `description` (required, the posting as free text) and `requirements_text` (optional, the "what the position needs" part when it is not already inside the description). When the job is accepted, the response MUST be HTTP 201 with the job: its `id`, `title`, `company` (null when not given), `description`, `requirements_text` (null when not given), `status` (`uploaded`, see `job-processing`), `error` (null), `extraction` (null, see `job-extraction`) and `created_at`. Surrounding whitespace in the text fields is removed, and an empty `company` or `requirements_text` is stored as null.

#### Scenario: Full posting
- **WHEN** a client sends a title, a company, a description and a requirements text
- **THEN** the response is 201 with all of them, status `uploaded`, no error and no extraction

#### Scenario: Only the required fields
- **WHEN** a client sends only a title and a description
- **THEN** the response is 201 with `company` and `requirements_text` null

#### Scenario: Blank optional fields
- **WHEN** a client sends `"company": "  "` and `"requirements_text": ""`
- **THEN** both are stored as null

### Requirement: Job input is validated
The system MUST reject with HTTP 422 and the error code `validation_error` (the standard envelope, naming each invalid field and never repeating what was sent) a request in which: `title` or `description` is missing or blank; `title` or `company` is longer than 200 characters; `description` or `requirements_text` is longer than 50,000 characters; or an unknown field is present.

#### Scenario: Missing description
- **WHEN** a client sends a title without a description
- **THEN** the response is 422 with `validation_error` naming `description`

#### Scenario: Blank title
- **WHEN** the title is only whitespace
- **THEN** the response is 422 naming `title`

#### Scenario: Too long
- **WHEN** the description has 50,001 characters
- **THEN** the response is 422 naming `description`, and a description of exactly 50,000 characters is accepted

#### Scenario: Unknown field
- **WHEN** the body contains a field that is not part of the job
- **THEN** the response is 422 naming that field

#### Scenario: Text is not echoed
- **WHEN** a request is rejected
- **THEN** the response body contains none of the submitted text

### Requirement: Postings are not de-duplicated
Every successful `POST /jobs` SHALL create a new job, even when its content equals an existing job.

#### Scenario: Same posting twice
- **WHEN** a client sends the same body twice
- **THEN** both responses are 201 with different `id`s and `GET /jobs` lists two jobs

### Requirement: Jobs can be listed
The system SHALL expose `GET /jobs`, which returns HTTP 200 with every stored job, newest first, each with `id`, `title`, `company`, `status`, `error` and `created_at`, and without `description`, `requirements_text` or `extraction`.

#### Scenario: Two jobs
- **WHEN** two jobs are stored
- **THEN** the response lists both, the most recently created first, and no item contains `description`, `requirements_text` or `extraction`

#### Scenario: None stored
- **WHEN** no job is stored
- **THEN** the response is 200 with an empty list

### Requirement: A job can be read
The system SHALL expose `GET /jobs/{id}`, which returns HTTP 200 with the same body as the creation response, including the current `status`, the `error` of a failed run and the `extraction` of the last successful processing (null if there was none). An unknown `id` MUST give HTTP 404 with the error code `job_not_found`. An `id` that is not a valid UUID MUST give HTTP 422.

#### Scenario: Round trip
- **WHEN** a job is created and then read by its `id`
- **THEN** the body equals the creation response body

#### Scenario: Unknown id
- **WHEN** a client reads a UUID that does not exist
- **THEN** the response is 404 with code `job_not_found`

### Requirement: A job can be deleted
The system SHALL expose `DELETE /jobs/{id}`, which removes the job and its stored requirements (see `job-requirements`) and returns HTTP 204. An unknown `id` MUST give HTTP 404 with the error code `job_not_found`.

#### Scenario: Delete
- **WHEN** a client deletes an existing job
- **THEN** the response is 204 and `GET /jobs/{id}` returns 404

#### Scenario: Delete a processed job
- **WHEN** a client deletes a job that has requirements
- **THEN** the response is 204 and no requirement of that job remains

#### Scenario: Delete twice
- **WHEN** a client deletes the same job twice
- **THEN** the second response is 404

### Requirement: Job content is private
The system MUST NOT write the title, company, description, requirements text or any extracted content of a job (requirements, responsibilities, keywords) to logs, and error responses MUST NOT contain them. Logs MAY contain identifiers, counts, error codes and durations.

#### Scenario: Normal use
- **WHEN** jobs are created, read, processed and deleted
- **THEN** no log entry contains text from a posting

#### Scenario: Debug logging while processing
- **WHEN** the log level is DEBUG and a job is processed
- **THEN** no log entry from the application, the provider SDKs or the HTTP library contains posting text, extracted content or the prompt
