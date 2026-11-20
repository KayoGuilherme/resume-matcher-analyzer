# Spec Delta

## Purpose

Defines how a verified build of `main` is published as a container image to GitHub Container Registry, without deploying it anywhere.

## ADDED Requirements

### Requirement: Image is published only after CI passes on main
A CD workflow SHALL run for pushes to `main` and MUST publish an image only when the CI workflow completed successfully for that same commit. It MUST NOT run for pull requests or other branches.

#### Scenario: CI passed on main
- **WHEN** CI completes successfully for a commit on `main`
- **THEN** the CD workflow builds and publishes the image for that commit

#### Scenario: CI failed on main
- **WHEN** CI fails for a commit on `main`
- **THEN** no image is published for that commit

#### Scenario: Pull request
- **WHEN** a pull request is opened or updated
- **THEN** the CD workflow does not publish anything

### Requirement: Image is tagged with the commit SHA and latest
The published image SHALL be pushed to `ghcr.io` under the repository's name, built from the commit that passed CI, and tagged with that full commit SHA and with `latest`.

#### Scenario: Tags after merge
- **WHEN** a commit is merged to `main` and published
- **THEN** the image is available in `ghcr.io` with the tag equal to that commit's SHA and the tag `latest`

### Requirement: Publishing uses only the built-in token with scoped write access
The CD workflow SHALL authenticate to the registry using only the built-in `GITHUB_TOKEN`. The permission to write packages MUST be granted only to the job that pushes the image, and every other permission MUST be read-only.

#### Scenario: No additional secrets
- **WHEN** the CD workflow is inspected
- **THEN** it references no secret other than `GITHUB_TOKEN`

#### Scenario: Scoped package permission
- **WHEN** the CD workflow is inspected
- **THEN** `packages: write` appears only on the publishing job

### Requirement: No deployment
The CD workflow MUST NOT deploy the image to any server or hosting target.

#### Scenario: Publish only
- **WHEN** the CD workflow finishes
- **THEN** the only external effect is the image pushed to the registry
