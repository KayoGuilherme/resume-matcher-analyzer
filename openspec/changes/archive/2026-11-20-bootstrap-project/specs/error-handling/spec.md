# Spec Delta

## Purpose

Defines a single, consistent way for business-rule failures to be reported to API clients, so that features raise typed domain errors and never build HTTP responses themselves.

## ADDED Requirements

### Requirement: Domain errors map to HTTP responses in one place
The system SHALL define a base domain error type. Any domain error raised during a request SHALL be converted to a JSON HTTP response by one central handler, using the status code and message carried by the error.

#### Scenario: Domain error is raised
- **WHEN** a request handler raises a domain error carrying a status code and message
- **THEN** the response has that status code and a JSON body containing the error's code and message

#### Scenario: Base domain error has a default
- **WHEN** a domain error is raised without a more specific status code
- **THEN** the response status is a client/server error code defined by the base error type (not 200)

### Requirement: Error responses do not leak internals
Error responses MUST NOT include stack traces, personal data, or document content.

#### Scenario: Unexpected exception
- **WHEN** an unexpected exception occurs while handling a request
- **THEN** the client receives a generic 500 response without exception details
