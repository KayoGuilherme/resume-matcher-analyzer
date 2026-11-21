# Spec Delta

## Purpose

Splits an extracted resume into small, verbatim pieces and stores them with their vectors, so later matching can search the resume's content semantically and quote evidence from it.

## ADDED Requirements

### Requirement: Bullets and skills lines become chunks
For a resume extraction the system SHALL create one chunk for each experience bullet, each project bullet and each skills line, and for nothing else. A chunk has its section (`experience`, `projects` or `skills`), the id of the experience it belongs to (none for projects and skills), its position within the resume, and its verbatim text, unchanged. Empty or whitespace-only text MUST NOT become a chunk.

#### Scenario: Chunks per item
- **WHEN** an extraction has two experiences with three and two bullets, one project with two bullets and two skills lines
- **THEN** nine chunks are created, five with section `experience`, two with `projects` and two with `skills`

#### Scenario: Provenance
- **WHEN** a chunk comes from a bullet of an experience
- **THEN** its experience id is the id of that experience in the extraction, and its text equals the bullet

#### Scenario: Nothing to chunk
- **WHEN** an extraction has no bullets and no skills lines
- **THEN** no chunks are created and the resume can still become ready

### Requirement: Chunks are stored with their vectors and embedding model
Each chunk SHALL be stored with its vector and the name of the embedding model that produced it. Vectors MUST be searchable by cosine distance with an approximate-nearest-neighbor (HNSW) index. The size of the vector column comes from `EMBEDDING_DIMENSION`. Deleting a resume MUST delete its chunks.

#### Scenario: Model recorded
- **WHEN** chunks are stored with `EMBEDDING_MODEL=bge-m3`
- **THEN** every chunk row says `bge-m3`

#### Scenario: Similarity search
- **WHEN** a vector is compared with the stored chunks by cosine distance
- **THEN** the query can use the HNSW index and returns the closest chunks first

#### Scenario: Delete
- **WHEN** a resume with chunks is deleted
- **THEN** none of its chunks remain

### Requirement: Chunks are replaced as a whole
When a resume is processed again, its old chunks, its extraction and its new status MUST be replaced in one transaction, so a reader never sees a mix of old and new chunks, and a failed run MUST leave the previous chunks untouched.

#### Scenario: Reprocess
- **WHEN** a ready resume is processed again and succeeds
- **THEN** only the new chunks exist afterwards

#### Scenario: Failed reprocess
- **WHEN** a ready resume is processed again and embedding fails
- **THEN** the previous chunks still exist unchanged

### Requirement: Startup checks the vector dimension
At startup, when the database holds the chunk table, the application SHALL compare the vector size of its embedding column with `EMBEDDING_DIMENSION`. On a mismatch the application MUST refuse to start with a message that states both sizes and points to the documented procedure for changing the embedding model. When the table does not exist yet (migrations not applied) or the database is not reachable, the application MUST start and log a warning that the check was skipped.

#### Scenario: Mismatch
- **WHEN** the column has 1024 dimensions and `EMBEDDING_DIMENSION=768`
- **THEN** startup fails with a message stating 1024 and 768 and referring to the re-embedding procedure

#### Scenario: Match
- **WHEN** both are 1024
- **THEN** the application starts normally

#### Scenario: Migrations not applied
- **WHEN** the chunk table does not exist
- **THEN** the application starts and logs that the dimension check was skipped

### Requirement: The embedding-model change procedure is documented
The documentation SHALL describe how to change the embedding model: that vectors from different models are not comparable, how to find chunks made by another model, what to do when the dimension is unchanged (process the resumes again) and when it changes (a new migration that resizes the column and index, then process again).

#### Scenario: Procedure present
- **WHEN** the README is read
- **THEN** it contains the procedure for both cases
