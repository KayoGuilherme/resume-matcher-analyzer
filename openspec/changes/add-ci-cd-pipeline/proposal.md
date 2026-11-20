# Proposal

## Why

Most code in this repo will be written by AI agents, so quality must not depend on someone remembering to run checks. Every PR needs automatic, strict verification (lint, types, tests, migrations, image build) before it can merge, and `main` needs a reproducible, published container image. The `bootstrap-project` change is applied, so there is now a skeleton worth protecting.

## What Changes

- Add `.github/workflows/ci.yml`: five parallel jobs (`lint`, `typecheck`, `test`, `integration`, `docker-build`) on `pull_request` and `push` to `main`, with `concurrency` cancelling outdated PR runs, `contents: read` permissions, Python 3.12 and cached `uv`. Target: under 5 minutes total.
- `test` job: unit tests only (no database), branch coverage via `pytest-cov`, fails under 80% (threshold lives in `pyproject.toml`), coverage table in the job summary, `coverage.xml` uploaded as an artifact.
- `integration` job: `pgvector/pgvector:pg16` service container; runs `alembic upgrade head` on the empty database, `alembic check` (models vs. migrations), then the tests marked `integration`.
- `docker-build` job: builds the `Dockerfile` without pushing, with layer cache.
- Add the `integration` pytest marker, exclude it from the default `pytest` run, and add one `/health` integration test against the real database.
- Wire SQLAlchemy declarative metadata into `alembic/env.py` (today `target_metadata = None`, which makes `alembic check` fail with "doesn't provide a MetaData object"). No tables are added; the metadata is simply empty until the first model exists, and from then on a model without a migration fails CI.
- Add `pytest-cov` to the dev dependency group (explicitly requested; no other dependency is added).
- Add `.github/workflows/pr-lint.yml`: PR title must be a Conventional Commit (`amannn/action-semantic-pull-request`, types `feat, fix, docs, refactor, test, chore, ci, build, perf`), a title length limit, every commit in the PR checked with commitlint (config in the repo), and error messages that explain how to fix it.
- Add `.github/workflows/cd.yml`: on `push` to `main`, only after CI succeeded for that commit, build and push the image to `ghcr.io` tagged with the commit SHA and `latest`. `packages: write` only in that job. No deployment.
- Add `.github/dependabot.yml` (weekly: `uv`, `docker`, `github-actions`) and `.github/pull_request_template.md`.
- Pin every third-party action to at least a major version.
- Docs: add a "Commits and PRs" section to `.claude/CLAUDE.md`; add a "Repository settings (manual)" section to `README.md` (branch protection, required checks, squash-only merges with PR title as commit message).
- Workflows use no secrets; only the built-in `GITHUB_TOKEN`.

## Capabilities

### New Capabilities
- `ci-pipeline`: the CI workflow, its five jobs, triggers, concurrency, permissions, coverage gate, integration-test marker and database-backed checks.
- `pr-conventions`: Conventional Commits enforcement on PR titles and PR commits, with actionable failure messages.
- `image-publishing`: the CD workflow that publishes the verified image to ghcr.io from `main`.
- `repository-hygiene`: Dependabot updates, the PR template, action pinning, the "no secrets in workflows" rule and the documented manual repository settings.

### Modified Capabilities
- `database-migrations`: adds the requirement that the Alembic environment knows the application's models so that models and migrations can be checked for drift (`alembic check`).

## Impact

- New files: `.github/workflows/{ci,pr-lint,cd}.yml`, `.github/dependabot.yml`, `.github/pull_request_template.md`, `commitlint.config.mjs` (repo root), `tests/health/test_router_integration.py`.
- Modified: `pyproject.toml` (pytest `addopts`/marker, coverage config, `pytest-cov`), `uv.lock`, `src/app/core/db.py` (declarative `Base`), `alembic/env.py` (`target_metadata`), `.claude/CLAUDE.md`, `README.md`.
- No runtime behavior or HTTP API changes. No folder-structure changes.
- Manual GitHub settings (branch protection etc.) cannot be applied by a workflow and are documented only.
- Out of scope: real deployment, pre-commit hooks, vulnerability and secret scanning, evals in CI, release tagging and changelog automation.
