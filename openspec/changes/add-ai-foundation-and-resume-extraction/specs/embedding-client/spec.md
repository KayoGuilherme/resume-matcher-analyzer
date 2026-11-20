# Spec Delta

## Purpose

Gives the application one provider-agnostic way to turn text into multilingual vectors, so hosted and local embedding models can be switched by configuration only, independently from the LLM, and a model that does not fit the database is caught early.

## ADDED Requirements

### Requirement: The embeddings provider is chosen by configuration only
The system SHALL support the embedding providers `local` (a model run inside the application process), `openai` and `openai_compatible` (any server speaking the OpenAI embeddings API, such as Ollama, through a configurable base URL). The embeddings configuration (`EMBEDDING_PROVIDER`, `EMBEDDING_MODEL`, `EMBEDDING_DIMENSION`, `EMBEDDING_API_KEY`, `EMBEDDING_BASE_URL`) MUST be independent from the LLM configuration, so that any combination of LLM and embeddings providers works. Changing it MUST NOT require a code change, and only the embeddings layer may contact an embeddings provider.

#### Scenario: Independent providers
- **WHEN** `LLM_PROVIDER=anthropic` and `EMBEDDING_PROVIDER=openai_compatible` are set
- **THEN** completions go to Anthropic and embeddings go to the configured compatible server

#### Scenario: Unknown provider
- **WHEN** `EMBEDDING_PROVIDER` is not one of the three values
- **THEN** a validation error names `EMBEDDING_PROVIDER` and lists the accepted values

### Requirement: Texts are embedded in batches
The system SHALL embed a list of texts in one call and return one vector per text, in the same order. Lists longer than the provider batch limit MUST be split transparently. An empty list MUST return an empty list without contacting the provider.

#### Scenario: Order is kept
- **WHEN** three texts are embedded
- **THEN** three vectors are returned and the i-th vector belongs to the i-th text

#### Scenario: Large list
- **WHEN** more texts than the batch limit are embedded
- **THEN** the provider receives several requests and the caller receives all vectors in order

#### Scenario: Empty list
- **WHEN** an empty list is embedded
- **THEN** an empty list is returned and no request is made

### Requirement: Vectors must have the configured dimension
Every returned vector MUST have exactly `EMBEDDING_DIMENSION` numbers. A vector of another size MUST make the call fail with a typed dimension error that names the configured and the received dimension, and no vector may be stored.

#### Scenario: Provider returns another size
- **WHEN** `EMBEDDING_DIMENSION` is 1024 and the provider returns vectors of 768 numbers
- **THEN** the call fails with the dimension error stating 1024 and 768

### Requirement: Embeddings failures are typed and transient ones are retried
The embeddings layer SHALL report failures through typed errors for transient failures, authentication failures and timeouts, with the same retry rules as the LLM layer: transient failures are retried with exponential backoff and then raised, authentication failures and timeouts are not retried; any other provider rejection is reported as the general embeddings error that is the parent of these. No provider SDK exception MUST reach callers. Calls MUST be logged with provider, model, number of texts and duration, and MUST NOT log the texts or vectors.

#### Scenario: Transient then success
- **WHEN** the provider answers 500 once and then succeeds
- **THEN** the vectors are returned

#### Scenario: Authentication failure
- **WHEN** the provider answers 401
- **THEN** the call fails with the authentication error and is not retried

#### Scenario: Content is not logged
- **WHEN** texts are embedded with DEBUG logging
- **THEN** no log entry contains any of the texts

### Requirement: The model supports Portuguese and English
The documented default embedding model MUST be multilingual and support Portuguese and English. The documentation SHALL compare local and hosted options, recommend a default, and state that models other than the recommended one are the owner's responsibility to validate for Portuguese.

#### Scenario: Default configuration
- **WHEN** no embeddings variable is set
- **THEN** the defaults are the recommended multilingual model, its dimension (1024) and a local OpenAI-compatible server address

### Requirement: Local embeddings are an optional dependency
The packages that run local embedding models (which are large) SHALL be an optional dependency group that is not installed by default. When `EMBEDDING_PROVIDER=local` and the group is not installed, using embeddings MUST fail with a clear error that says which group to install, and the rest of the application MUST keep working. Local model inference MUST NOT block the event loop.

#### Scenario: Default install
- **WHEN** the project is installed without the optional group
- **THEN** the application and all default tests work, and the hosted and compatible providers work

#### Scenario: Local provider without the group
- **WHEN** `EMBEDDING_PROVIDER=local` and the group is not installed, and processing is requested
- **THEN** processing fails with a message naming the optional group to install

### Requirement: A deterministic fake exists for tests
The system SHALL provide a fake embeddings client that implements the same interface without network or model files. For a given dimension it MUST return the same vector for the same text, different vectors for different texts, and vectors of exactly the requested dimension.

#### Scenario: Deterministic
- **WHEN** the same text is embedded twice, possibly in different batches
- **THEN** the vectors are identical

#### Scenario: Different texts
- **WHEN** two different texts are embedded
- **THEN** the vectors differ

### Requirement: Missing embeddings configuration is reported only when embeddings are needed
The application MUST start without embeddings credentials. A request that needs embeddings while they are unusable (a hosted provider without an API key, a compatible provider without a base URL) MUST fail with HTTP 503 and the error code `ai_not_configured`, naming the missing setting.

#### Scenario: Hosted without key
- **WHEN** `EMBEDDING_PROVIDER=openai` and `EMBEDDING_API_KEY` is empty, and processing is requested
- **THEN** the response is 503 with code `ai_not_configured` naming `EMBEDDING_API_KEY`

### Requirement: A real embeddings provider can be exercised on demand
Tests marked `real_provider` SHALL also call the configured embeddings provider, be excluded from the default run and CI, and be skipped with a clear reason when it is not usable.

#### Scenario: Not configured
- **WHEN** the `real_provider` tests are selected and no embeddings provider is usable
- **THEN** the embeddings tests are skipped with the reason
