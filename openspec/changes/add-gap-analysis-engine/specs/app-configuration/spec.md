# Spec Delta

## ADDED Requirements

### Requirement: Analysis settings
The system SHALL read four settings from the environment: `ANALYSIS_TOP_K`, the number of resume chunks kept per requirement (whole number from 1 to 20, default 5); `ANALYSIS_MIN_SIMILARITY`, the lowest cosine similarity a chunk may have to be kept (number from 0 to 1, default 0.4); `ANALYSIS_MAX_REQUIREMENTS_PER_CALL`, the most requirements sent to the LLM in one call (whole number from 1 to 50, default 8); and `ANALYSIS_MAX_LLM_CALLS`, the most LLM calls one analysis may make (whole number from 1 to 100, default 10). A value outside its range or not of its type MUST make startup fail with a validation error that names the setting. All four MUST be listed in `.env.example` with a short comment, and the one about similarity MUST say that it depends on the embedding model.

#### Scenario: Defaults
- **WHEN** the application starts without these variables
- **THEN** the top-k is 5, the minimum similarity 0.4, 8 requirements per call and 10 calls per analysis

#### Scenario: Overrides
- **WHEN** `ANALYSIS_TOP_K=3` and `ANALYSIS_MIN_SIMILARITY=0.55` are set
- **THEN** retrieval keeps at most 3 chunks per requirement, each with a similarity of at least 0.55

#### Scenario: Out of range
- **WHEN** `ANALYSIS_MIN_SIMILARITY` is `1.5` or `ANALYSIS_TOP_K` is `0`
- **THEN** startup fails with a validation error that names that setting

#### Scenario: Not a number
- **WHEN** `ANALYSIS_MAX_LLM_CALLS` is `many`
- **THEN** startup fails with a validation error that names `ANALYSIS_MAX_LLM_CALLS`

#### Scenario: Example file
- **WHEN** `.env.example` is read
- **THEN** it lists the four settings with their defaults
