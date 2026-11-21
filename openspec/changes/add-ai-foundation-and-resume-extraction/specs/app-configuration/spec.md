# Spec Delta

## ADDED Requirements

### Requirement: LLM settings
The system SHALL read these LLM settings from the environment: `LLM_PROVIDER` (`anthropic`, `openai` or `openai_compatible`; no default, so the application runs without an LLM), `LLM_MODEL` (no default), `LLM_API_KEY` (no default), `LLM_BASE_URL` (no default; required for `openai_compatible`, optional for `openai`), `LLM_TIMEOUT_SECONDS` (default 120, must be a positive number) and `LLM_TEMPERATURE` (default 0; a number from 0 to 2, or empty to send no temperature). An invalid value MUST make startup fail with a validation error naming the setting. API keys MUST be treated as secrets: never shown in error messages, logs or responses.

#### Scenario: Defaults
- **WHEN** no `LLM_*` variable is set
- **THEN** the application starts, no LLM is configured, the timeout is 120 seconds and the temperature is 0

#### Scenario: Local server
- **WHEN** `LLM_PROVIDER=openai_compatible`, `LLM_BASE_URL=http://localhost:11434/v1` and `LLM_MODEL=llama3.1` are set
- **THEN** the LLM settings are valid without an API key

#### Scenario: Invalid timeout
- **WHEN** `LLM_TIMEOUT_SECONDS` is `0` or `abc`
- **THEN** startup fails with a validation error that names `LLM_TIMEOUT_SECONDS`

#### Scenario: Temperature disabled
- **WHEN** `LLM_TEMPERATURE` is set to an empty value
- **THEN** the temperature setting is none and the application starts

#### Scenario: Secret not echoed
- **WHEN** a setting is invalid while `LLM_API_KEY` holds a value
- **THEN** the validation error does not contain the key

### Requirement: Embedding settings
The system SHALL read these embedding settings from the environment, independent from the LLM settings: `EMBEDDING_PROVIDER` (`local`, `openai` or `openai_compatible`; default `openai_compatible`), `EMBEDDING_MODEL` (default `bge-m3`), `EMBEDDING_DIMENSION` (default 1024; a whole number from 1 to 2000, the limit of the vector index), `EMBEDDING_API_KEY` (no default) and `EMBEDDING_BASE_URL` (no default; the `openai_compatible` provider then uses the local Ollama address `http://localhost:11434/v1`, and `openai` uses the OpenAI endpoint). An invalid value MUST make startup fail with a validation error naming the setting. API keys MUST be treated as secrets.

#### Scenario: Defaults
- **WHEN** no `EMBEDDING_*` variable is set
- **THEN** the provider is `openai_compatible`, the model `bge-m3`, the dimension 1024, no base URL is set, and requests go to `http://localhost:11434/v1`

#### Scenario: Hosted override
- **WHEN** `EMBEDDING_PROVIDER=openai`, `EMBEDDING_MODEL=text-embedding-3-small` and `EMBEDDING_DIMENSION=1024` are set
- **THEN** embeddings use that provider and model and 1024-number vectors

#### Scenario: Invalid dimension
- **WHEN** `EMBEDDING_DIMENSION` is `0`, `2001` or `abc`
- **THEN** startup fails with a validation error that names `EMBEDDING_DIMENSION`

### Requirement: Example file documents the AI settings
`.env.example` SHALL list every `LLM_*` and `EMBEDDING_*` variable with placeholder values only, and give ready-to-copy example blocks for Anthropic, OpenAI and a local Ollama server (the Ollama block reaching the host from the container through `host.docker.internal`), for both the LLM and the embeddings.

#### Scenario: Examples present
- **WHEN** `.env.example` is read
- **THEN** it contains all ten variables and an Anthropic, an OpenAI and an Ollama example, and no real secret
