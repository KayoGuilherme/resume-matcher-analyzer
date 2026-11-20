# Spec Delta

## Purpose

Defines how the API and its pgvector-enabled PostgreSQL database are packaged and started locally with Docker, so any developer can run the stack with one command.

## ADDED Requirements

### Requirement: One-command local stack
The repository SHALL provide a Docker Compose setup with an `api` service and a `db` service (PostgreSQL with the pgvector extension). `docker compose up --build` MUST start both without errors, and the API MUST be reachable on port 8000 of the host.

#### Scenario: Stack starts and is healthy
- **WHEN** a developer copies `.env.example` to `.env` and runs `docker compose up --build`
- **THEN** both services start and `curl localhost:8000/health` returns 200 reporting the database as ok

#### Scenario: Migrations run inside the container
- **WHEN** `docker compose exec api alembic upgrade head` is run on the running stack
- **THEN** it succeeds and the `vector` extension exists in the database

### Requirement: API waits for a healthy database
The `db` service SHALL define a health check, and the `api` service MUST NOT start until the database reports healthy.

#### Scenario: Slow database startup
- **WHEN** the database takes several seconds to accept connections
- **THEN** the API container starts only after the database health check passes

### Requirement: Database data persists
Database data SHALL be stored in a named volume so that it survives container restarts and recreation.

#### Scenario: Restart containers
- **WHEN** the stack is stopped and started again without removing volumes
- **THEN** previously stored database data is still present

### Requirement: Minimal, non-root production image
The API image SHALL be built in multiple stages, run as a non-root user, and MUST NOT contain development dependencies.

#### Scenario: Container user
- **WHEN** the API container is running
- **THEN** its process runs as a non-root user

#### Scenario: No dev tooling in image
- **WHEN** the final image is inspected
- **THEN** test, lint and type-check tools are not installed in it
