# Spec Delta

## ADDED Requirements

### Requirement: Migrations stay in sync with the models
The migration environment SHALL know the application's database models so that drift between the models and the migrations can be detected with `alembic check`. The check MUST succeed on a database migrated to head when the models and migrations agree, and MUST fail when a model change has no corresponding migration.

#### Scenario: In sync
- **WHEN** `alembic upgrade head` has been applied and `alembic check` is run, and the models match the migrations
- **THEN** the check succeeds

#### Scenario: Model without migration
- **WHEN** a model is added or changed without a new migration and `alembic check` is run
- **THEN** the check fails and reports the detected difference

#### Scenario: No models yet
- **WHEN** the application has no models and `alembic check` is run on a migrated database
- **THEN** the check succeeds
