# Spec Delta

## Purpose

Gives the application one provider-agnostic way to ask a language model for structured data, so hosted providers and local models can be switched by configuration only and every provider quirk (structured output support, sampling parameters, retries, invalid output) is handled in one shared place.

## ADDED Requirements

### Requirement: The provider is chosen by configuration only
The system SHALL support the LLM providers `anthropic`, `openai` and `openai_compatible` (any server that speaks the OpenAI chat API, such as Ollama, LM Studio or vLLM, reached through a configurable base URL). Changing `LLM_PROVIDER`, `LLM_MODEL`, `LLM_API_KEY` or `LLM_BASE_URL` MUST change which provider answers without any change to application code. Code that needs a model MUST depend only on the provider-independent interface, never on a specific provider, and only the LLM layer may contact an LLM provider.

#### Scenario: Switch from hosted to local
- **WHEN** the environment changes from `LLM_PROVIDER=anthropic` to `LLM_PROVIDER=openai_compatible` with a `LLM_BASE_URL` and `LLM_MODEL` for a local server and the application is restarted
- **THEN** resume processing sends its requests to the local server and no code was changed

#### Scenario: Unknown provider
- **WHEN** `LLM_PROVIDER` is set to a value that is not one of the three
- **THEN** the application reports a validation error that names `LLM_PROVIDER` and lists the accepted values

### Requirement: Missing LLM configuration is reported only when an LLM is needed
The application MUST start and serve requests that do not use an LLM (health, upload, list, read, delete) when no LLM is configured. A request that needs an LLM while none is usable (no provider, no model, a hosted provider without an API key, or `openai_compatible` without a base URL) MUST fail with HTTP 503 and the error code `ai_not_configured`, whose message names the missing setting and never contains a secret.

#### Scenario: No LLM configured
- **WHEN** `LLM_PROVIDER` is not set and a client calls `GET /health`
- **THEN** the response is 200

#### Scenario: Hosted provider without a key
- **WHEN** `LLM_PROVIDER=openai` and `LLM_API_KEY` is empty, and processing is requested
- **THEN** the response is 503 with code `ai_not_configured` and a message naming `LLM_API_KEY`

#### Scenario: Compatible server without a base URL
- **WHEN** `LLM_PROVIDER=openai_compatible` and `LLM_BASE_URL` is empty, and processing is requested
- **THEN** the response is 503 with code `ai_not_configured` and a message naming `LLM_BASE_URL`

#### Scenario: Local server without a key
- **WHEN** `LLM_PROVIDER=openai_compatible`, a base URL and a model are set and no API key is set
- **THEN** the LLM is considered configured (local servers do not need a key)

### Requirement: Structured output is validated against a schema
The system SHALL expose a call that takes a prompt and a Pydantic model class and returns a validated instance of that class. Whatever the provider returns, a result MUST only reach the caller after it has been validated against the schema; a raw string or unvalidated dictionary MUST NOT be returned.

#### Scenario: Valid output
- **WHEN** the model answers with JSON that matches the schema
- **THEN** the caller receives an instance of the schema class

#### Scenario: JSON wrapped in text
- **WHEN** the model answers with valid JSON inside a Markdown code fence or after a short sentence
- **THEN** the JSON is extracted and validated, and the caller receives the instance

### Requirement: Native structured output is used when available, with a JSON-in-prompt fallback
For each provider the system SHALL use its native structured-output mechanism when the provider and model support it (tool use for Anthropic, a JSON schema response format for OpenAI and compatible servers). When the provider or model rejects the native mechanism, the system MUST fall back to asking for JSON in the prompt and parsing the answer, for that and the following calls, without failing the request and without any provider-specific code in the callers.

#### Scenario: Native mechanism used
- **WHEN** the provider supports native structured output
- **THEN** the request carries the schema through the native mechanism and the prompt does not need to ask for JSON

#### Scenario: Provider does not support it
- **WHEN** a local server answers that the schema or tool parameter is not supported
- **THEN** the call is repeated with the schema described in the prompt, the answer is parsed and validated, and the caller receives the instance

#### Scenario: Fallback is remembered
- **WHEN** a fallback happened once for the configured provider and model
- **THEN** later calls from the same running application go straight to JSON-in-prompt without trying the native mechanism again

### Requirement: Invalid output gets one repair attempt, then a typed error
When the answer cannot be parsed as JSON or does not validate against the schema, the system MUST make exactly one repair attempt that tells the model what was wrong with its previous answer. If the repaired answer is also invalid, the call MUST fail with the typed error for invalid output. The repair logic MUST be the same for every provider.

#### Scenario: Repair succeeds
- **WHEN** the first answer misses a required field and the repair answer is valid
- **THEN** the caller receives the valid instance and the provider was called twice

#### Scenario: Repair fails
- **WHEN** both answers are invalid
- **THEN** the call fails with the invalid-output error and the provider was called exactly twice

#### Scenario: No repair needed
- **WHEN** the first answer is valid
- **THEN** the provider is called exactly once

### Requirement: Sampling parameters are sent only when supported
The system SHALL send a temperature only when one is configured (`LLM_TEMPERATURE`, default 0). When the provider or model rejects the temperature parameter, the call MUST be repeated without it and later calls MUST omit it. An empty `LLM_TEMPERATURE` MUST mean that no temperature is ever sent.

#### Scenario: Default temperature
- **WHEN** `LLM_TEMPERATURE` is not set
- **THEN** requests carry temperature 0

#### Scenario: Model rejects temperature
- **WHEN** the provider answers that temperature is not supported for the model
- **THEN** the call is repeated without temperature, succeeds, and later calls do not send it

#### Scenario: Temperature disabled
- **WHEN** `LLM_TEMPERATURE` is set to an empty value
- **THEN** no request carries a temperature

### Requirement: Failures are typed and transient ones are retried
The LLM layer SHALL report failures only through these typed errors: transient (rate limit, server error, connection problem), invalid output, authentication (missing, wrong or forbidden credentials), and timeout (no answer within `LLM_TIMEOUT_SECONDS`); any other provider rejection (for example an unknown model or an oversized request) MUST be reported as the general LLM error that is the parent of these. Transient failures MUST be retried with exponential backoff up to a fixed number of attempts and then raised as the transient error. Authentication failures and timeouts MUST NOT be retried. No provider SDK exception MUST reach callers.

#### Scenario: Transient then success
- **WHEN** the provider answers 503 once and then succeeds
- **THEN** the caller receives the result, after one backoff wait

#### Scenario: Transient exhausted
- **WHEN** the provider keeps answering 429
- **THEN** the call fails with the transient error after the maximum number of attempts

#### Scenario: Authentication failure
- **WHEN** the provider answers 401
- **THEN** the call fails immediately with the authentication error and is not retried

#### Scenario: Timeout
- **WHEN** the provider does not answer within the configured timeout
- **THEN** the call fails with the timeout error and is not retried

### Requirement: LLM calls are logged without content
For every LLM call the system SHALL log the provider, the model, the token usage when the provider reports it, the duration and the outcome (success, repaired, fallback, or the error type). Logs MUST NOT contain prompts, model answers, resume text or API keys, at any log level, including from the provider SDKs and the HTTP library.

#### Scenario: Successful call
- **WHEN** a call succeeds
- **THEN** one log entry has the provider, model, token counts and duration, and contains no prompt or answer text

#### Scenario: Debug logging
- **WHEN** the log level is DEBUG and a call is made
- **THEN** no log entry contains the prompt, the answer or the API key

### Requirement: A fake client exists for tests
The system SHALL provide a fake LLM client that implements the same interface, returns scripted answers (valid instances, raw text to be validated, or errors to raise), records the calls it received, and never uses the network. Unit tests of code that needs an LLM MUST use it.

#### Scenario: Scripted answer
- **WHEN** a fake is scripted with an instance and called
- **THEN** it returns that instance and records the prompt it received

#### Scenario: Scripted failure
- **WHEN** a fake is scripted to fail with the timeout error
- **THEN** the call raises that error

### Requirement: A real provider can be exercised on demand
The test suite SHALL contain tests marked `real_provider` that call whichever LLM provider is configured in the environment. They MUST be excluded from the default test run and from CI, and MUST be skipped with a clear reason when no LLM is configured.

#### Scenario: Not configured
- **WHEN** the `real_provider` tests are selected and no LLM is configured
- **THEN** they are skipped and the reason says which setting is missing

#### Scenario: Configured
- **WHEN** an LLM is configured and the `real_provider` tests are selected
- **THEN** a small structured request is sent to that provider and the result validates
