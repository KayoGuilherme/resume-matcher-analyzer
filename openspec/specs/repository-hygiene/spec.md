# repository-hygiene Specification

## Purpose

Defines repository-level practices that keep automation safe and contributions consistent: dependency update automation, a pull request checklist, pinned third-party actions, no secrets in workflows, and documented manual repository settings.

## Requirements

### Requirement: Automated weekly dependency updates
The repository SHALL configure Dependabot to open weekly update pull requests for the Python (`uv`) dependencies, the Docker base images referenced by the Dockerfile, and the GitHub Actions used by the workflows.

#### Scenario: Ecosystems covered
- **WHEN** the Dependabot configuration is inspected
- **THEN** it lists the `uv`, `docker` and `github-actions` ecosystems, each with a weekly schedule

### Requirement: Pull request template
The repository SHALL provide a pull request template with a short checklist covering: the linked OpenSpec change, tests added or updated, no secrets or personal data committed, and compliance with the rules in `.claude/CLAUDE.md`.

#### Scenario: New pull request
- **WHEN** a contributor opens a pull request
- **THEN** the description is pre-filled with the checklist

### Requirement: Third-party actions are pinned
Every third-party GitHub Action used in a workflow SHALL be pinned to at least a major version tag (for example `owner/action@v5`), never to a branch name such as `main` or to an unversioned reference.

#### Scenario: Unpinned action
- **WHEN** a workflow references a third-party action without a version
- **THEN** it violates this requirement and must be fixed before merging

### Requirement: Workflows contain no secrets
Workflows MUST NOT contain secrets, tokens or credentials, and MUST NOT reference repository or organization secrets other than the built-in `GITHUB_TOKEN`. Throwaway values for ephemeral CI services (such as the CI database password) are allowed because they protect nothing.

#### Scenario: Secret references
- **WHEN** the workflow files are searched for `secrets.`
- **THEN** the only match is `secrets.GITHUB_TOKEN`

### Requirement: Manual repository settings are documented
The README SHALL include a "Repository settings (manual)" section listing the GitHub settings that workflows cannot apply: protecting `main`; requiring pull requests and disallowing direct pushes; requiring the status checks `lint`, `typecheck`, `test`, `integration`, `docker-build` and the PR-rules checks; and allowing squash merging only, with the pull request title as the commit message. `.claude/CLAUDE.md` SHALL include a "Commits and PRs" section stating: Conventional Commits, small pull requests, one OpenSpec change per pull request, and never push to `main`.

#### Scenario: Maintainer sets up a new repository
- **WHEN** a maintainer follows the README section
- **THEN** they can configure the repository so that merging requires all CI jobs and PR-rules checks to pass

#### Scenario: Agent reads project rules
- **WHEN** an agent reads `.claude/CLAUDE.md`
- **THEN** it finds the commit and PR conventions, including that pushing to `main` is forbidden
