# Spec Delta

## Purpose

Stores every extracted requirement of a job as its own row with its vector, so later matching can search the requirements semantically and quote the posting text they came from.

## ADDED Requirements

### Requirement: Each requirement is stored with its vector
For a job extraction the system SHALL store one row per requirement in the `job_requirements` table with: its `id` (the same as in the extraction), the job it belongs to, its position in the posting, `text`, `category`, `priority`, `priority_unclear`, `min_years`, `keywords`, `source_text`, its vector and the name of the embedding model that produced it. The vector is the embedding of the requirement's `text`. A job with no requirements stores no rows and can still become ready.

#### Scenario: One row per requirement
- **WHEN** an extraction has five requirements
- **THEN** five rows are stored for the job, each with the same id as in the extraction

#### Scenario: Model recorded
- **WHEN** rows are stored with `EMBEDDING_MODEL=bge-m3`
- **THEN** every row says `bge-m3`

#### Scenario: No requirements
- **WHEN** an extraction has no requirements
- **THEN** no rows are stored and no embedding request is made

#### Scenario: Provenance
- **WHEN** a row is read
- **THEN** its `source_text` is the posting's own wording and its `position` is the order of the requirements in the extraction

### Requirement: Vectors are searchable by cosine distance
The vector column SHALL have the size given by `EMBEDDING_DIMENSION` and MUST be searchable by cosine distance with an approximate-nearest-neighbor (HNSW) index.

#### Scenario: Similarity search
- **WHEN** a vector is compared with the stored requirements by cosine distance
- **THEN** the query can use the HNSW index and returns the closest requirements first

### Requirement: Requirements are replaced as a whole
When a job is processed again, its old requirements, its extraction and its new status MUST be replaced in one transaction, so a reader never sees a mix of old and new requirements, and a failed run MUST leave the previous requirements untouched.

#### Scenario: Reprocess
- **WHEN** a ready job is processed again and succeeds
- **THEN** only the new requirements exist afterwards

#### Scenario: Failed reprocess
- **WHEN** a ready job is processed again and embedding fails
- **THEN** the previous requirements still exist unchanged

### Requirement: Requirements are deleted with their job
Deleting a job MUST delete its requirements.

#### Scenario: Delete
- **WHEN** a job with requirements is deleted
- **THEN** none of its requirements remain

### Requirement: Startup checks the requirements vector dimension
At startup, when the database holds the `job_requirements` table, the application SHALL compare the vector size of its embedding column with `EMBEDDING_DIMENSION`, in addition to the check for resume chunks. On a mismatch the application MUST refuse to start with a message that states both sizes and points to the documented procedure for changing the embedding model, which MUST cover this table too. When the table does not exist yet or the database is not reachable, the application MUST start and log a warning that the check was skipped.

#### Scenario: Mismatch
- **WHEN** the column has 1024 dimensions and `EMBEDDING_DIMENSION=768`
- **THEN** startup fails with a message stating 1024 and 768 and referring to the re-embedding procedure

#### Scenario: Migrations not applied
- **WHEN** the `job_requirements` table does not exist
- **THEN** the application starts and logs that the check was skipped

#### Scenario: Procedure covers both tables
- **WHEN** the README's procedure for changing the embedding model is read
- **THEN** it says to resize and re-embed both `resume_chunk` and `job_requirements`
