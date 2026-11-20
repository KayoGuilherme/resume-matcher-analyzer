# Spec Delta

## ADDED Requirements

### Requirement: Request validation errors use the same error envelope
When a request body, path or query parameter fails validation, the system SHALL respond with HTTP 422 and a JSON body in the same envelope as domain errors, with the error code `validation_error` and a message that names each invalid field and the reason. The message MUST NOT contain the submitted values.

#### Scenario: Invalid field
- **WHEN** a request has a field that fails validation
- **THEN** the response is 422 with `{"error": {"code": "validation_error", "message": ...}}` and the message names the field and the reason

#### Scenario: Several invalid fields
- **WHEN** a request has more than one invalid field
- **THEN** the single response message names all of them

#### Scenario: Submitted values are not echoed
- **WHEN** a request fails validation and a submitted value is text that must remain private
- **THEN** the response body does not contain that text
