# Proposal

## Why

Resumes are stored and parsed to plain text, but nothing can read them yet: there is no LLM or embeddings access, no prompt management, and no structured form of a resume. Every later capability (jobs, matching, scoring) needs the same two things: a structured `Resume` whose every claim is traceable to the resume text, and searchable vectors of its content. This change builds the shared AI layer and uses it to produce both.

The AI layer must be provider-agnostic. The owner wants to move between hosted providers (Anthropic, OpenAI) and local models (Ollama, LM Studio, vLLM) by changing environment variables only, because resumes are personal data and some runs should never leave the machine.

## What Changes

- **LLM layer** `ai/llm/` (replaces the single `llm.py` of the project layout): an `LLMClient` protocol with `generate_structured(prompt, schema)`, typed errors (transient, invalid output, auth, timeout), Anthropic and OpenAI adapters (the OpenAI adapter also serves any OpenAI-compatible server through `LLM_BASE_URL`, which is how local models work), a `FakeLLMClient`, and a factory used with `Depends`. Validation, the one repair retry, the fallback from native structured output to JSON-in-prompt, optional sampling parameters, backoff and logging live in one shared wrapper, not in the adapters.
- **Embeddings layer** `ai/embeddings/` (replaces `embeddings.py`): an `EmbeddingClient` protocol with batch embedding; local (sentence-transformers, optional dependency group), `openai` and `openai_compatible` (for example Ollama) adapters; a deterministic `FakeEmbeddingClient`. Configured independently from the LLM. Recommended default: `bge-m3` (1024 dimensions, multilingual) served by a local Ollama; the comparison is below.
- **Prompt loader** for versioned `ai/prompts/*.md` files, and the first prompt (`resume_extraction`). Every extraction result records the prompt version and the LLM model.
- **Resume extraction** into a Pydantic `Resume` (summary, skills, experiences with start/end month and bullets, education, languages, certifications, projects; no contact details). Bullet text must appear verbatim in the resume text or is retried and then dropped. Total experience is computed in code from dates, merging overlapping jobs.
- **Chunking and vectors**: each bullet and each skills line becomes a chunk (section, experience id, verbatim text, embedding, embedding model name) in a new `resume_chunk` table with an HNSW cosine index. The vector size comes from `EMBEDDING_DIMENSION`; startup fails with a clear message when it does not match the database column.
- **Processing status**: the resume gets `uploaded -> processing -> ready | failed`; `POST /resumes/{id}/process` starts a FastAPI `BackgroundTasks` job (202); `GET /resumes/{id}` shows the status and, when ready, the extraction.
- **Docs and config**: `.env.example` with all `LLM_*` and `EMBEDDING_*` variables and examples for Anthropic, OpenAI and a local Ollama; a README section for running with a local model (including how the Docker container reaches a server on the host, which needs `extra_hosts` on Linux) and for changing the embedding model; `.claude/CLAUDE.md` updated with the new structure and the rule that only `ai/llm/` and `ai/embeddings/` call providers.
- Tests: units use only the fakes; adapter tests mock the HTTP layer; one `real_provider` test runs against whatever provider is configured and is skipped otherwise.

Out of scope: jobs, matching, scoring, rewrite suggestions, OCR, authentication, a dedicated re-embedding command (the procedure is documented; see design.md).

### Embedding options (recommendation)

| Option | Dim. | PT + EN | Cost / privacy | Image impact |
|---|---|---|---|---|
| **`bge-m3` via Ollama** (`openai_compatible`) **(default)** | 1024 | strong, 100+ languages, 8k tokens, no query/passage prefixes needed | free; text stays on the machine | none (HTTP only) |
| `bge-m3` / `multilingual-e5-base` via sentence-transformers (`local`) | 1024 / 768 | strong | free; in-process, no server to run | large: pulls torch (optional group, off by default) |
| `multilingual-e5-small` via sentence-transformers | 384 | good | free; in-process; lowest CPU/RAM | large (same group) |
| OpenAI `text-embedding-3-small` | 1536 (can be reduced to 1024 with `dimensions`) | good | about $0.02 per 1M tokens; resume text goes to the provider | none |
| OpenAI `text-embedding-3-large` | 3072 (reducible) | very good | higher cost; same privacy trade-off | none |
| Anthropic | n/a, Anthropic offers no embeddings model | | | |

Recommendation: `bge-m3` through an OpenAI-compatible local server. It is the best multilingual retrieval quality among free options, keeps personal data local, and leaves the default Docker image small. Hosted `text-embedding-3-small` is the easy alternative when no local server is available. 1024 dimensions fits under pgvector's 2000-dimension limit for HNSW indexes on `vector`.

## Capabilities

### New Capabilities
- `llm-client`: the provider-agnostic LLM protocol, adapters, structured output with fallback and repair, optional sampling parameters, retry with backoff, typed errors, fake client, factory and logging rules.
- `embedding-client`: the provider-agnostic embeddings protocol, adapters, batching, dimension checks, fake client, factory, and the optional local dependency group.
- `prompt-management`: versioned prompt files loaded from `ai/prompts/`, never inline in code.
- `resume-extraction`: structured `Resume` extraction with verbatim validation, no contact details, provenance (prompt version, model), and code-computed experience duration.
- `resume-chunking`: chunks and vectors per bullet and skills line, the `resume_chunk` table with HNSW cosine index, the stored embedding model, and the startup dimension check.
- `resume-processing`: the status lifecycle, `POST /resumes/{id}/process`, background execution, failure reporting, and re-processing.

### Modified Capabilities
- `resume-management`: resumes have a `status` and (when processed) an `extraction`; the list shows `status`; deleting a resume also removes its chunks.
- `app-configuration`: new `LLM_*` and `EMBEDDING_*` settings with defaults and validation, all listed in `.env.example`.
- `container-runtime`: the container can reach a model server on the host (`host.docker.internal`, including on Linux), and the image can optionally include the local-embeddings group while the default image stays small.

## Impact

- **Code**: new `src/app/ai/llm/`, `src/app/ai/embeddings/`, `src/app/ai/prompts/`, `src/app/ai/extraction/`, `src/app/ai/pipeline.py`, `src/app/core/retry.py`; changes in `src/app/resumes/` (models, repository, service, router, schemas), `src/app/core/config.py`, `src/app/main.py` (startup check) and `core/db.py` (vector codec if needed); Alembic migration `0004` (status columns, `resume_chunk`, HNSW index).
- **API**: new `POST /resumes/{id}/process`; `GET /resumes`, `GET /resumes/{id}` gain `status` (and `extraction` on the detail). Additive only; no existing field changes.
- **Dependencies (new, each justified)**:
  - `anthropic` and `openai`: the official SDKs give typed errors for auth, rate limit and timeout, connection handling, and an injectable `http_client` so adapter tests mock the HTTP layer. Reimplementing both HTTP APIs by hand would duplicate that and drift from the APIs. SDK-internal retries are disabled so the shared layer owns retry behavior. `openai` also covers Ollama, LM Studio and vLLM, so no per-server client is needed.
  - `pgvector` (Python package): the SQLAlchemy `Vector` type and its asyncpg support, instead of hand-written casts and string formatting for vectors.
  - `sentence-transformers` in an **optional** extra `local-embeddings` only: needed for the `local` embeddings provider; heavy (torch), so it is not part of the default install or the default image.
  - Not added: LangChain or similar (project rule), `tenacity` (a ~30-line retry helper in `core/retry.py` is enough), a YAML library (prompt front matter is a two-key header parsed by hand).
- **Docs/config**: `.env.example`, README, `.claude/CLAUDE.md`, `docker-compose.yml`, `Dockerfile` (optional build argument), CI unchanged in shape (local-embeddings tests use an injected loader, so CI does not install torch).
- **Operations**: changing the embedding model needs re-processing the resumes (and a migration if the dimension changes); documented in the README.
