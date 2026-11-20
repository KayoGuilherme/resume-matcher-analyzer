# Spec Delta

## MODIFIED Requirements

### Requirement: A resume can be uploaded
The system SHALL expose `POST /resumes`, which accepts a `multipart/form-data` request with one file in the field `file`. When the file is accepted, the response MUST be HTTP 201 with the resume: its `id`, `original_filename` (the uploaded name without any directory part), `file_type` (`pdf` or `docx`), `size_bytes`, `sha256` (hex digest of the file bytes), `page_count` (a number, or null when unknown), `text` (the extracted text), `metadata` (at least the parser used, the character count and the word count), `issues` (the parsing-quality report, see `resume-parsing`), `status` (`uploaded` for a new resume, see `resume-processing`), `error` (null for a new resume), `extraction` (null for a new resume, see `resume-extraction`) and `created_at`.

#### Scenario: Clean PDF accepted
- **WHEN** a client uploads a clean one-column PDF resume
- **THEN** the response is 201 with `file_type` `pdf`, the extracted `text`, a `page_count`, the matching `sha256`, status `uploaded` and an empty `issues` list

#### Scenario: DOCX accepted
- **WHEN** a client uploads a DOCX resume
- **THEN** the response is 201 with `file_type` `docx` and the extracted `text`

#### Scenario: Problems are reported with the resume
- **WHEN** a client uploads a readable PDF with two columns
- **THEN** the response is 201 and `issues` contains the multi-column issue

#### Scenario: No file in the request
- **WHEN** a client sends `POST /resumes` without the `file` field
- **THEN** the response is 422 with a validation error that names the `file` field

### Requirement: Resumes can be listed
The system SHALL expose `GET /resumes`, which returns HTTP 200 with every stored resume, newest first, each with the same fields as the upload response except `text` and `extraction` (the `status` and `error` are included).

#### Scenario: Two resumes
- **WHEN** two resumes are stored and a client sends `GET /resumes`
- **THEN** the response lists both, the most recently created first, each with its `status`, and no item contains `text` or `extraction`

#### Scenario: None stored
- **WHEN** no resume is stored
- **THEN** the response is 200 with an empty list

### Requirement: A resume can be read
The system SHALL expose `GET /resumes/{id}`, which returns HTTP 200 with the same body as the upload response, including the current `status`, the `error` of a failed run, and the `extraction` of the last successful processing (null if there was none). An unknown `id` MUST give HTTP 404 with the error code `resume_not_found`. An `id` that is not a valid UUID MUST give HTTP 422.

#### Scenario: Round trip
- **WHEN** a resume is uploaded and then read by its `id`
- **THEN** the body equals the upload response body

#### Scenario: Processed resume
- **WHEN** a resume has been processed successfully and is read by its `id`
- **THEN** the body has status `ready` and the `extraction`

#### Scenario: Unknown id
- **WHEN** a client reads a UUID that does not exist
- **THEN** the response is 404 with code `resume_not_found`

### Requirement: A resume can be deleted
The system SHALL expose `DELETE /resumes/{id}`, which removes the resume record, its chunks (see `resume-chunking`) and its stored file and returns HTTP 204. An unknown `id` MUST give HTTP 404 with the error code `resume_not_found`. After deleting, the same file MUST be accepted again as a new resume (HTTP 201).

#### Scenario: Delete
- **WHEN** a client deletes an existing resume
- **THEN** the response is 204, `GET /resumes/{id}` returns 404, and the stored file no longer exists

#### Scenario: Delete a processed resume
- **WHEN** a client deletes a resume that has chunks
- **THEN** the response is 204 and no chunk of that resume remains

#### Scenario: Delete twice
- **WHEN** a client deletes the same resume twice
- **THEN** the second response is 404

#### Scenario: Upload again after delete
- **WHEN** a deleted file is uploaded again
- **THEN** the response is 201 with a new `id`

### Requirement: Resume content is private
The system MUST NOT write resume text, extracted resume content (bullets, skills, summary), prompts sent to a model, or uploaded file names to logs, and error responses MUST NOT contain resume text, extracted content or file names. Logs MAY contain identifiers, sizes, counts, issue codes and error codes. The extraction is returned only by the resume endpoints, to the client that asks for it.

#### Scenario: Accepted and rejected uploads
- **WHEN** resumes are uploaded, accepted and rejected, read and deleted
- **THEN** no log entry contains text from a resume or an uploaded file name

#### Scenario: Debug logging
- **WHEN** the log level is DEBUG and a PDF resume is uploaded
- **THEN** no log entry from the application or from the PDF library contains text from the resume

#### Scenario: Debug logging while processing
- **WHEN** the log level is DEBUG and a resume is processed
- **THEN** no log entry from the application, the provider SDKs or the HTTP library contains resume text, extracted content or the prompt

#### Scenario: Error responses
- **WHEN** an upload is rejected or processing fails
- **THEN** the error message does not contain the uploaded file name or any text from the file
