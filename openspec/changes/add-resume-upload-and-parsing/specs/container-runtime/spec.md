# Spec Delta

## ADDED Requirements

### Requirement: Uploaded files persist
Original resume files SHALL be stored in a named volume, separate from the database volume, so that they survive container restarts and recreation, and the non-root API user MUST be able to write to it.

#### Scenario: Upload works in the container
- **WHEN** the stack is running and a resume is uploaded
- **THEN** the upload succeeds and the file is written by the non-root API process

#### Scenario: Recreate containers
- **WHEN** the stack is stopped and started again without removing volumes
- **THEN** previously uploaded files are still present and the stored resumes can be deleted without error
