# Spec Delta

## Purpose

Provides one reusable way to turn the names of technologies and spoken languages, as people type them, into a canonical form so they can be compared and de-duplicated across the profile, resumes and jobs.

## ADDED Requirements

### Requirement: Names are compared in a canonical form
Normalization SHALL be case-insensitive, SHALL ignore leading and trailing whitespace and SHALL collapse internal runs of whitespace to a single space. The canonical form is lowercase. Normalizing an already canonical name MUST return it unchanged.

#### Scenario: Case and spacing
- **WHEN** the name `  Spring   BOOT ` is normalized as a stack
- **THEN** the result is `spring boot`

#### Scenario: Idempotent
- **WHEN** the result of a normalization is normalized again
- **THEN** the result is unchanged

### Requirement: Known aliases map to one canonical name
Normalization SHALL map known aliases to their canonical name. Stack names MUST include at least: `springboot` to `spring boot`, `postgres` to `postgresql`, and `js` to `javascript`. Language names MUST include at least: `pt` and `português` to `portuguese`, and `en` and `inglês` to `english`. Alias lookup MUST ignore case and accents.

#### Scenario: Stack aliases
- **WHEN** the stack names `springboot`, `Postgres` and `JS` are normalized
- **THEN** the results are `spring boot`, `postgresql` and `javascript`

#### Scenario: Language aliases
- **WHEN** the language names `pt`, `Português` and `portugues` are normalized
- **THEN** each result is `portuguese`

#### Scenario: Aliases are specific to the kind of name
- **WHEN** the stack name `pt` is normalized
- **THEN** the result is `pt`, because `pt` is a language alias only

### Requirement: Unknown names are only cleaned
A name without a known alias SHALL be returned in its cleaned canonical form (lowercase, whitespace trimmed and collapsed) with no other change.

#### Scenario: Unknown name
- **WHEN** the stack name `  Rust ` is normalized
- **THEN** the result is `rust`
