# database-migrations Specification

## Purpose

Defines how the database schema is versioned and evolved, and guarantees that the vector extension required by later features is available after migrating.

## Requirements

### Requirement: Schema changes are applied through versioned migrations
The system SHALL manage the database schema through versioned migrations that can be applied against a PostgreSQL database with `alembic upgrade head`, using the same environment-based database settings as the application.

#### Scenario: Apply migrations on an empty database
- **WHEN** `alembic upgrade head` is run against an empty PostgreSQL database
- **THEN** it completes successfully and records the current revision

#### Scenario: Re-running is safe
- **WHEN** `alembic upgrade head` is run again with no new migrations
- **THEN** it completes successfully and changes nothing

### Requirement: First migration enables pgvector
The first migration SHALL enable the `vector` extension using `CREATE EXTENSION IF NOT EXISTS vector`.

#### Scenario: Extension available after upgrade
- **WHEN** migrations are applied to the database
- **THEN** the `vector` extension is listed among the installed extensions

#### Scenario: Extension already installed
- **WHEN** the first migration runs on a database where the `vector` extension already exists
- **THEN** it completes without error
