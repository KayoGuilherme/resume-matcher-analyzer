# Spec Delta

## Purpose

Defines the automated verification every change must pass before merging: lint, type checks, unit tests with a coverage gate, database-backed integration checks and a container image build.

## ADDED Requirements

### Requirement: CI runs on pull requests and on main
The CI workflow SHALL run on every pull request and on every push to `main`. A newer run for the same pull request MUST cancel the outdated in-progress run. The workflow MUST request only read access to repository contents and MUST NOT use any secret other than the built-in `GITHUB_TOKEN`.

#### Scenario: Pull request opened
- **WHEN** a pull request is opened or updated
- **THEN** all CI jobs run and report their status on the pull request

#### Scenario: Superseded run
- **WHEN** new commits are pushed to a pull request while a CI run for it is in progress
- **THEN** the older run is cancelled and only the newest run completes

#### Scenario: Minimal permissions
- **WHEN** the CI workflow runs
- **THEN** its token has read-only access to repository contents and no other write permission

### Requirement: Independent parallel jobs
CI SHALL consist of the separate jobs `lint`, `typecheck`, `test`, `integration` and `docker-build`, running in parallel so that a failure identifies the failing check by job name. Each job MUST fail the run when its check fails.

#### Scenario: One check fails
- **WHEN** only the type check fails
- **THEN** the `typecheck` job fails, the other jobs report their own results independently, and the overall run is failed

### Requirement: Lint and format are enforced
The `lint` job SHALL fail when the code has lint violations or is not formatted according to the project's formatter configuration.

#### Scenario: Lint violation
- **WHEN** a pull request introduces a lint violation
- **THEN** the `lint` job fails

#### Scenario: Unformatted code
- **WHEN** a pull request contains code that the formatter would change
- **THEN** the `lint` job fails without modifying the code

### Requirement: Strict type check is enforced
The `typecheck` job SHALL fail when the type checker, in the project's strict configuration, reports any error in the application source.

#### Scenario: Type error
- **WHEN** a pull request introduces a type error in the application source
- **THEN** the `typecheck` job fails

### Requirement: Unit tests run without a database and enforce coverage
The `test` job SHALL run only the unit tests, which MUST pass without any database available, and measure branch coverage. It MUST fail when a test fails or when total coverage is below the configured threshold of 80%. The threshold MUST be configurable in `pyproject.toml`. The job SHALL show the coverage table in the job summary and upload the coverage report (`coverage.xml`) as an artifact, including when the job fails.

#### Scenario: Failing test
- **WHEN** a unit test fails
- **THEN** the `test` job fails

#### Scenario: Coverage below threshold
- **WHEN** total branch coverage is below the configured threshold
- **THEN** the `test` job fails and reports the measured and required coverage

#### Scenario: Coverage reporting
- **WHEN** the `test` job completes, whether it passes or fails the coverage gate
- **THEN** the coverage table is visible in the job summary and `coverage.xml` is available as a downloadable artifact

#### Scenario: Unit tests need no database
- **WHEN** the default test command is run on a machine with no database and no `DATABASE_URL` for a real database
- **THEN** it passes and does not run tests marked `integration`

### Requirement: Integration tests are marked and run against a real database
Tests that need a real database SHALL be marked `integration`, and the default test run MUST exclude them. The `integration` job SHALL start a PostgreSQL 16 service with the pgvector extension available, apply all migrations to the empty database, verify that the models and the migrations are in sync, and then run the tests marked `integration`. At least one integration test MUST verify that `GET /health` reports the database as ok against the real database.

#### Scenario: Migrations apply to an empty database
- **WHEN** the `integration` job starts with an empty database
- **THEN** applying all migrations succeeds

#### Scenario: Model change without migration
- **WHEN** a pull request changes a model without adding the matching migration
- **THEN** the models-versus-migrations check fails and the `integration` job fails

#### Scenario: Health against the real database
- **WHEN** the integration tests run against the migrated database
- **THEN** the `/health` integration test passes, showing HTTP 200 with the database reported as ok

### Requirement: Container image still builds
The `docker-build` job SHALL build the project's Dockerfile without pushing the image and MUST fail when the build fails. It SHALL reuse cached image layers between runs.

#### Scenario: Broken Dockerfile
- **WHEN** a pull request breaks the image build
- **THEN** the `docker-build` job fails

#### Scenario: Nothing is published from CI
- **WHEN** the `docker-build` job succeeds
- **THEN** no image is pushed to any registry

### Requirement: CI is fast
The full CI run SHALL be designed to complete in under 5 minutes in the normal case, running jobs in parallel and caching dependencies between runs.

#### Scenario: Warm cache
- **WHEN** a pull request changes only source code and dependency caches are warm
- **THEN** all CI jobs together finish in under 5 minutes
