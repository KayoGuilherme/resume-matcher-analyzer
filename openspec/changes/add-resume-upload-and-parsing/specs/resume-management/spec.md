# Spec Delta

## Purpose

Lets the candidate import resumes (PDF or DOCX), keep the original file and its extracted text, and list, read and delete them, rejecting files that an ATS could not read and never exposing resume content in logs.

## ADDED Requirements

### Requirement: A resume can be uploaded
The system SHALL expose `POST /resumes`, which accepts a `multipart/form-data` request with one file in the field `file`. When the file is accepted, the response MUST be HTTP 201 with the resume: its `id`, `original_filename` (the uploaded name without any directory part), `file_type` (`pdf` or `docx`), `size_bytes`, `sha256` (hex digest of the file bytes), `page_count` (a number, or null when unknown), `text` (the extracted text), `metadata` (at least the parser used, the character count and the word count), `issues` (the parsing-quality report, see `resume-parsing`) and `created_at`.

#### Scenario: Clean PDF accepted
- **WHEN** a client uploads a clean one-column PDF resume
- **THEN** the response is 201 with `file_type` `pdf`, the extracted `text`, a `page_count`, the matching `sha256` and an empty `issues` list

#### Scenario: DOCX accepted
- **WHEN** a client uploads a DOCX resume
- **THEN** the response is 201 with `file_type` `docx` and the extracted `text`

#### Scenario: Problems are reported with the resume
- **WHEN** a client uploads a readable PDF with two columns
- **THEN** the response is 201 and `issues` contains the multi-column issue

#### Scenario: No file in the request
- **WHEN** a client sends `POST /resumes` without the `file` field
- **THEN** the response is 422 with a validation error that names the `file` field

### Requirement: The real file type is checked, not the name
The system MUST decide the file type from the file content: a PDF starts with the `%PDF-` signature, and a DOCX is a ZIP package that contains a Word document part. The file extension and the declared content type MUST NOT decide acceptance. Files of any other type MUST be rejected with HTTP 415 and the error code `unsupported_file_type`, whose message says that only PDF and DOCX are accepted.

#### Scenario: Fake PDF
- **WHEN** a client uploads a text file named `resume.pdf`
- **THEN** the response is 415 with code `unsupported_file_type` and nothing is stored

#### Scenario: Other ZIP file
- **WHEN** a client uploads a ZIP archive that is not a Word document, named `resume.docx`
- **THEN** the response is 415 with code `unsupported_file_type`

#### Scenario: Wrong extension, right content
- **WHEN** a client uploads a valid PDF named `resume.txt`
- **THEN** the file is accepted as `pdf`

#### Scenario: Unsupported format
- **WHEN** a client uploads a PNG image
- **THEN** the response is 415 with code `unsupported_file_type`

### Requirement: Uploads have a maximum size
The system SHALL reject a file larger than the configured maximum upload size (5 MB by default) with HTTP 413 and the error code `file_too_large`, whose message states the limit. A file exactly at the limit MUST be accepted. A rejected file MUST NOT be stored.

#### Scenario: File over the limit
- **WHEN** a client uploads a valid PDF of 5 MB plus one byte with the default limit
- **THEN** the response is 413 with code `file_too_large`

#### Scenario: File at the limit
- **WHEN** a client uploads a valid resume of exactly the maximum size
- **THEN** the file is accepted

#### Scenario: Configured limit
- **WHEN** the maximum upload size is configured as 1 MB and a client uploads a 2 MB file
- **THEN** the response is 413 and the message states 1 MB

### Requirement: Empty and unreadable files are rejected
The system MUST reject a zero-byte file with HTTP 422 and the error code `empty_file`. It MUST reject a file with a valid signature that cannot be opened (corrupted or password-protected) with HTTP 422 and the error code `unreadable_file`, whose message explains that an ATS could not open it either.

#### Scenario: Zero bytes
- **WHEN** a client uploads an empty file
- **THEN** the response is 422 with code `empty_file`

#### Scenario: Corrupted PDF
- **WHEN** a client uploads a file that starts with `%PDF-` but is truncated and cannot be parsed
- **THEN** the response is 422 with code `unreadable_file` and nothing is stored

### Requirement: Files without extractable text are rejected with an ATS explanation
When no text can be extracted from a file, the system MUST reject it with HTTP 422 and the error code `no_extractable_text`, and MUST NOT store it. The message SHALL explain the ATS problem: an ATS reads the text layer of a resume, so a file whose content is only images (for example a scanned or exported-as-image resume) is read as blank, and the fix is to export a text-based PDF or DOCX from the original editor. When the file contains images but no text, the message MUST also say that the file looks scanned or image-only.

#### Scenario: Scanned PDF
- **WHEN** a client uploads a PDF whose pages contain only images
- **THEN** the response is 422 with code `no_extractable_text` and a message that says the file looks scanned or image-only and that an ATS would read it as blank

#### Scenario: Blank document
- **WHEN** a client uploads a DOCX with no text
- **THEN** the response is 422 with code `no_extractable_text`

#### Scenario: Nothing is kept on rejection
- **WHEN** an upload is rejected for any reason
- **THEN** no resume record exists for it and no file for it is left in storage

### Requirement: Identical files are not duplicated
Resumes SHALL be unique by the sha256 of the file bytes. Uploading bytes that are already stored MUST return the existing resume with HTTP 200 (and not create a record, a second stored file or a new `created_at`). The first upload of given bytes returns 201.

#### Scenario: Same file twice
- **WHEN** a client uploads the same file twice
- **THEN** the first response is 201, the second is 200 with the same `id`, and `GET /resumes` lists one resume

#### Scenario: Same bytes, different name
- **WHEN** a client uploads the same bytes under another file name
- **THEN** the response is 200 with the existing resume

#### Scenario: Concurrent identical uploads
- **WHEN** two identical uploads arrive at the same time
- **THEN** exactly one resume exists afterwards and both responses return that resume

### Requirement: The original file is stored
For an accepted resume, the system SHALL keep the original file, unchanged, in the configured file storage, under a name derived from its content hash (not from the uploaded name), so that the stored file can be identified and removed with its resume. If the file cannot be stored, the upload MUST fail without leaving a resume record.

#### Scenario: Stored file matches
- **WHEN** a resume is accepted
- **THEN** the storage holds exactly the uploaded bytes, and its name does not contain the uploaded file name

#### Scenario: Storage failure
- **WHEN** the storage cannot write the file
- **THEN** the response is a generic 500 error and no resume record exists

### Requirement: Resumes can be listed
The system SHALL expose `GET /resumes`, which returns HTTP 200 with every stored resume, newest first, each with the same fields as the upload response except `text`.

#### Scenario: Two resumes
- **WHEN** two resumes are stored and a client sends `GET /resumes`
- **THEN** the response lists both, the most recently created first, and no item contains `text`

#### Scenario: None stored
- **WHEN** no resume is stored
- **THEN** the response is 200 with an empty list

### Requirement: A resume can be read
The system SHALL expose `GET /resumes/{id}`, which returns HTTP 200 with the same body as the upload response. An unknown `id` MUST give HTTP 404 with the error code `resume_not_found`. An `id` that is not a valid UUID MUST give HTTP 422.

#### Scenario: Round trip
- **WHEN** a resume is uploaded and then read by its `id`
- **THEN** the body equals the upload response body

#### Scenario: Unknown id
- **WHEN** a client reads a UUID that does not exist
- **THEN** the response is 404 with code `resume_not_found`

### Requirement: A resume can be deleted
The system SHALL expose `DELETE /resumes/{id}`, which removes the resume record and its stored file and returns HTTP 204. An unknown `id` MUST give HTTP 404 with the error code `resume_not_found`. After deleting, the same file MUST be accepted again as a new resume (HTTP 201).

#### Scenario: Delete
- **WHEN** a client deletes an existing resume
- **THEN** the response is 204, `GET /resumes/{id}` returns 404, and the stored file no longer exists

#### Scenario: Delete twice
- **WHEN** a client deletes the same resume twice
- **THEN** the second response is 404

#### Scenario: Upload again after delete
- **WHEN** a deleted file is uploaded again
- **THEN** the response is 201 with a new `id`

### Requirement: Resume content is private
The system MUST NOT write resume text or uploaded file names to logs, and error responses MUST NOT contain resume text or file names. Logs MAY contain identifiers, sizes, counts and issue codes.

#### Scenario: Accepted and rejected uploads
- **WHEN** resumes are uploaded, accepted and rejected, read and deleted
- **THEN** no log entry contains text from a resume or an uploaded file name

#### Scenario: Debug logging
- **WHEN** the log level is DEBUG and a PDF resume is uploaded
- **THEN** no log entry from the application or from the PDF library contains text from the resume

#### Scenario: Error responses
- **WHEN** an upload is rejected
- **THEN** the error message does not contain the uploaded file name or any text from the file
