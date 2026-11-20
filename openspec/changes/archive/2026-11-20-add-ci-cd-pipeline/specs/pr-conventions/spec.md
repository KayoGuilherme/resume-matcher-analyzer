# Spec Delta

## Purpose

Defines the Conventional Commits rules enforced on pull request titles and commit messages, so history and squash-merge commit messages stay consistent and machine-readable.

## ADDED Requirements

### Requirement: Pull request title follows Conventional Commits
A PR-rules workflow SHALL run on pull requests (including when the title is edited) and MUST fail when the pull request title is not a Conventional Commit using one of the types `feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `ci`, `build`, `perf`. The title MUST NOT exceed 72 characters.

#### Scenario: Valid title
- **WHEN** a pull request is titled `feat: add resume upload endpoint`
- **THEN** the title check passes

#### Scenario: Non-conventional title
- **WHEN** a pull request is titled `Added some stuff`
- **THEN** the title check fails

#### Scenario: Unknown type
- **WHEN** a pull request is titled `feature: add upload`
- **THEN** the title check fails because `feature` is not an allowed type

#### Scenario: Title too long
- **WHEN** a pull request title is longer than 72 characters
- **THEN** the title check fails

#### Scenario: Title edited
- **WHEN** a failing title is edited to a valid one
- **THEN** the title check runs again and passes

### Requirement: Every commit in the pull request follows Conventional Commits
The PR-rules workflow SHALL check every commit message in the pull request against a Conventional Commits configuration stored in the repository, allowing the same types and the same header length limit as the title, and MUST fail when any commit does not comply.

#### Scenario: Non-conventional commit
- **WHEN** a pull request contains a commit with the message `wip stuff`
- **THEN** the commit check fails and names the offending commit

#### Scenario: All commits valid
- **WHEN** every commit message in the pull request is a valid Conventional Commit
- **THEN** the commit check passes

### Requirement: Failures explain how to fix them
When a PR-rules check fails, its output SHALL state the expected format, list the allowed types, and say how to fix it (edit the title, or amend or reword the commit and force-push).

#### Scenario: Reader sees the fix
- **WHEN** the title check fails
- **THEN** the failure message shows an example such as `feat: short description`, the allowed types and the length limit

### Requirement: PR rules use minimal permissions
The PR-rules workflow SHALL request only read access to repository contents and pull requests and MUST NOT use any secret other than the built-in `GITHUB_TOKEN`.

#### Scenario: Permissions
- **WHEN** the PR-rules workflow runs
- **THEN** its token cannot write to the repository or pull requests
