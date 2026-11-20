# Spec Delta

## ADDED Requirements

### Requirement: Resume upload settings
The system SHALL read two settings from the environment: `RESUME_MAX_UPLOAD_BYTES`, the maximum accepted upload size in bytes (default 5242880, which is 5 MB), and `RESUME_STORAGE_DIR`, the directory where original resume files are kept (default `data/resumes`). A maximum size that is not a positive whole number MUST make startup fail with a validation error naming the setting. Both settings MUST be listed in `.env.example`.

#### Scenario: Defaults
- **WHEN** the application starts without these variables
- **THEN** the maximum upload size is 5 MB and files are stored under `data/resumes`

#### Scenario: Overrides
- **WHEN** `RESUME_MAX_UPLOAD_BYTES=1048576` and `RESUME_STORAGE_DIR=/data/resumes` are set
- **THEN** uploads over 1 MB are rejected and files are stored under `/data/resumes`

#### Scenario: Invalid size
- **WHEN** `RESUME_MAX_UPLOAD_BYTES` is `0` or `abc`
- **THEN** startup fails with a validation error that names `RESUME_MAX_UPLOAD_BYTES`
