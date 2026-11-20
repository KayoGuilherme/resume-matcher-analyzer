# Spec Delta

## Purpose

Defines how the service obtains its configuration: exclusively from environment variables, with a documented example file and no committed secrets.

## ADDED Requirements

### Requirement: Configuration comes only from the environment
The system SHALL read all configuration (including the database connection settings) from environment variables. It MUST NOT depend on values hard-coded in source or on committed configuration files containing real secrets.

#### Scenario: Settings loaded from environment
- **WHEN** the application starts with the required environment variables set
- **THEN** it uses those values for its configuration

#### Scenario: Required setting missing
- **WHEN** the application starts and a required environment variable (such as the database URL) is not set
- **THEN** startup fails with a clear validation error naming the missing setting

### Requirement: Example environment file without secrets
The repository SHALL provide a `.env.example` listing every environment variable the application reads, using placeholder values only. The real `.env` file MUST be excluded from version control and from the Docker build context.

#### Scenario: Example file covers all settings
- **WHEN** a developer copies `.env.example` to `.env`
- **THEN** the stack can be started locally without any other configuration step

#### Scenario: Real secrets are not committed
- **WHEN** the repository's ignore rules are inspected
- **THEN** `.env` is ignored by version control and by the Docker build context
