# Spec Delta

## ADDED Requirements

### Requirement: The API container can reach a model server on the host
The Docker Compose setup SHALL make the name `host.docker.internal` resolve to the host machine inside the `api` container on Linux as well as on Docker Desktop, so that `LLM_BASE_URL` and `EMBEDDING_BASE_URL` can point to a model server (such as Ollama) running on the host. The README MUST explain this, including that the server must listen on an address reachable from the container.

#### Scenario: Host name resolves
- **WHEN** the stack runs on Linux and a process in the `api` container resolves `host.docker.internal`
- **THEN** it resolves to the host's gateway address

#### Scenario: Local model through the container
- **WHEN** Ollama runs on the host and `.env` uses `http://host.docker.internal:11434/v1` for the LLM and the embeddings
- **THEN** processing a resume from the container reaches Ollama

### Requirement: The default image stays small
The default image SHALL NOT include the local-embeddings dependency group (the heavy machine-learning packages). A build argument MUST allow including it on request, and the README MUST say how.

#### Scenario: Default build
- **WHEN** the image is built without options
- **THEN** the sentence-transformers and torch packages are not installed in it

#### Scenario: Opt-in build
- **WHEN** the image is built with the documented argument
- **THEN** the local embeddings provider works inside the container
