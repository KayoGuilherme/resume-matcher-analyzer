# health-check Specification

## Purpose

Lets operators, Docker and orchestrators verify that the API process is running and that its database is reachable.

## Requirements

### Requirement: Health endpoint reports app and database status
The system SHALL expose `GET /health`. When the application is running and the database is reachable, it MUST respond with HTTP 200 and a JSON body reporting the app status as ok and the database status as ok.

#### Scenario: Database reachable
- **WHEN** a client sends `GET /health` and the database answers a connectivity check
- **THEN** the response is 200 with a JSON body showing the app status and the database status both as ok

### Requirement: Health endpoint signals database outage
When the database is unreachable, `GET /health` MUST respond with HTTP 503 and a JSON body reporting the database status as unavailable.

#### Scenario: Database unreachable
- **WHEN** a client sends `GET /health` and the database connectivity check fails
- **THEN** the response is 503 with a JSON body showing the database status as unavailable

### Requirement: Health endpoint is safe to expose
The health response MUST NOT include connection strings, credentials, or error details from the database driver.

#### Scenario: Failure details hidden
- **WHEN** the database check fails with a driver error containing a connection string
- **THEN** the response body does not contain that error text or connection string
