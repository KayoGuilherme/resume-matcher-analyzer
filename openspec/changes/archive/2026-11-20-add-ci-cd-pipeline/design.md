# Design

## Context

See proposal.md for motivation. Observed current state (bootstrap-project applied):

- `pyproject.toml` has dev deps `pytest, pytest-asyncio, httpx, ruff, mypy`; ruff and mypy (strict, `files = ["src"]`) are configured; pytest uses `testpaths = ["tests"]`, `pythonpath = ["src"]`. No `pytest-cov`, no markers, no coverage config.
- Unit tests mock the DB session (`tests/health/test_router.py` overrides `get_session`; `tests/conftest.py` builds `Settings` with a fake URL), so they already run without a database.
- `alembic/env.py` sets `target_metadata = None`. With no metadata, `alembic check` aborts with "environment script doesn't provide a MetaData object", so the "model change without a migration fails CI" criterion cannot work until metadata exists. There are no models yet; `src/app/core/db.py` has the engine/session code but no declarative `Base`.
- Only one migration (`0001`, enables pgvector). `Settings` requires `DATABASE_URL`; `alembic/env.py` reads it through `get_settings()`.
- `Dockerfile` is multi-stage with `uv 0.13.6` copied from `ghcr.io/astral-sh/uv`; `docker-compose.yml` uses `pgvector/pgvector:pg16`.
- The project directory is not a git repository yet, so the workflows cannot run until it is pushed to GitHub; local validation is limited to linting the YAML, running the commands the jobs run, and a local Docker build.

## Goals / Non-Goals

**Goals:**
- One command per check in CI, identical to what a developer runs locally (`uv run ...`), so failures are reproducible.
- Strict by default, fast (< 5 min), and readable: one job per concern, parallel.
- Least privilege: read-only default token, `packages: write` only on the publish job, no secrets beyond `GITHUB_TOKEN`.

**Non-Goals:**
- Deployment, release tagging, changelog automation, pre-commit hooks, vulnerability/secret scanning, evals in CI (see proposal).
- Matrix builds (one Python version, one OS).
- Enforcing the repository settings from code; they are documented in the README.

## Decisions

**1. `alembic check` needs real metadata: add `Base` to `core/db.py` and point `env.py` at it.**
Add `class Base(DeclarativeBase)` to `src/app/core/db.py` and set `target_metadata = Base.metadata` in `alembic/env.py`. This stays inside the existing folder structure and is not a new migration (no schema change). Alternative: `alembic check` against `None` metadata (fails today) or skipping the check until the first model exists (loses the safety net exactly when it is needed, since agents will write the models). Models in feature folders must be imported before metadata is read; when the first model lands, its change must import it from `env.py` (or an aggregating import). This is a known follow-up, noted in tasks as a comment in `env.py`.

**2. Test selection by marker, configured in `pyproject.toml`.**
Register the `integration` marker and set `addopts = ["-m", "not integration"]`, so a bare `uv run pytest` is always database-free. The integration job runs `pytest -m integration`; a later `-m` on the command line overrides the one in `addopts`. Alternative: separate `tests/integration/` directory only. Rejected because the project mirrors `src/app` under `tests/`, and a marker lets an integration test live next to the feature it covers (`tests/health/test_router_integration.py`). Integration tests fail (not skip) when `DATABASE_URL` is missing, so a misconfigured job cannot pass silently.

**3. Coverage: configuration in `pyproject.toml`, invocation in CI.**
`[tool.coverage.run] branch = true, source_pkgs = ["app"]` and `[tool.coverage.report] fail_under = 80, show_missing = true`. CI runs `uv run pytest --cov --cov-report=xml`; `pytest-cov` enforces `fail_under` (so the threshold is configurable in one place). A following `if: always()` step appends `uv run coverage report --format=markdown` to `$GITHUB_STEP_SUMMARY`, and `actions/upload-artifact` (also `if: always()`) uploads `coverage.xml`. Coverage is not added to `addopts`, so local runs stay fast and the integration job is not measured. The threshold may need a quick measurement at implementation time; the current suite is small but fully mocked, so ≥ 80% is expected, and if not, the missing tests are added in this change rather than lowering the threshold.

**4. Job shape of `ci.yml`.**
Top-level `permissions: contents: read`; `concurrency: group: ci-${{ github.workflow }}-${{ github.ref }}`, `cancel-in-progress: ${{ github.event_name == 'pull_request' }}` (never cancel runs on `main`, since CD depends on them). Each Python job: `actions/checkout`, `astral-sh/setup-uv` with `enable-cache: true` and Python 3.12, `uv sync --locked`. `--locked` makes CI fail when `uv.lock` is out of date with `pyproject.toml`. The `integration` job uses a `services.postgres` container (`pgvector/pgvector:pg16`, `pg_isready` health check options) and job-level env `DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/ats`; those credentials are throwaway values for an ephemeral container, not secrets. Steps: `alembic upgrade head`, `alembic check`, `pytest -m integration`. The `docker-build` job uses `docker/setup-buildx-action` and `docker/build-push-action` with `push: false`, `cache-from/cache-to: type=gha`.

**5. CD trigger: `workflow_run` on CI, not a duplicate pipeline.**
`cd.yml` triggers on `workflow_run` of `CI` (`types: [completed]`, `branches: [main]`) and the publish job has `if: github.event.workflow_run.conclusion == 'success' && github.event.workflow_run.event == 'push'`. It checks out and tags `github.event.workflow_run.head_sha` (not the branch tip, which may have moved on). Alternatives: (a) call CI as a reusable workflow from `cd.yml` — re-runs all checks on every merge, slower and duplicates CI; (b) `on: push` plus polling for CI status — fragile. The trade-off of `workflow_run` is that the workflow file only takes effect once it is on the default branch; that is acceptable. The publish job: `permissions: contents: read, packages: write`, `docker/login-action` to `ghcr.io` with `github.actor` and `GITHUB_TOKEN`, `docker/build-push-action` with tags `ghcr.io/<lowercased repository>:<sha>` and `:latest`. The image name must be lowercase; the job computes it with a shell step (`${GITHUB_REPOSITORY,,}`). It reuses the `gha` build cache. A `concurrency` group on `cd` without cancellation keeps `latest` moving in merge order.

**6. PR rules: two jobs in `pr-lint.yml` on `pull_request` (`opened, edited, synchronize, reopened`).**
- `title`: `amannn/action-semantic-pull-request` with the nine types, `subjectPattern` requiring a non-empty subject, and a custom `subjectPatternError`; an extra shell step fails titles longer than 72 characters with a message showing the format, the allowed types and how to edit the title (the action itself has no length option). `pull-requests: read` only.
- `commits`: `wagoid/commitlint-github-action` reading `commitlint.config.mjs` from the repo root, which extends `@commitlint/config-conventional` and overrides `type-enum` (same nine types) and `header-max-length` (72). Using the action means no `package.json`/Node dependency in this Python repo. Its `helpURL` points to the "Commits and PRs" section in CLAUDE.md, and the failure text explains how to reword (`git commit --amend` / `git rebase -i` and force-push). `contents: read, pull-requests: read`. Merge commits are ignored by commitlint by default.
- Uses `pull_request` (not `pull_request_target`): no checkout of untrusted code with elevated tokens, and the title is available on the event payload.

**7. Action pinning and updates.**
Every third-party action is pinned to a major tag (e.g. `@v5`); the exact current majors are checked when writing the files (not guessed in this plan). Dependabot (`github-actions` ecosystem, weekly) keeps them current. Pinning to commit SHAs is stricter but out of scope here (the requirement is "at least a major version"). Dependabot `uv` covers `pyproject.toml`/`uv.lock`; `docker` covers the `Dockerfile` (including the `uv` image reference). `docker-compose.yml` is not covered (separate `docker-compose` ecosystem); left out deliberately to keep to the requested three.

**8. Documentation.**
README gets "Repository settings (manual)", a checklist of GitHub settings; CLAUDE.md gets a short "Commits and PRs" section. The README test instructions are updated to mention the `integration` marker.

## Risks / Trade-offs

- [Workflows cannot be run before the repo is on GitHub (no git repo here)] → validate locally with `actionlint` (if available) and by running each job's commands and a local `docker build`; do the final acceptance on a real PR (task group 6).
- [Required status checks only block merging once configured in GitHub] → documented manual settings; job names are fixed (`lint`, `typecheck`, `test`, `integration`, `docker-build`) so they match the required-check list. Renaming a job silently un-requires it.
- [`alembic check` can miss models that are never imported by `env.py`] → documented in `env.py`; the first change that adds a model must import it. Revisit with a registry import when more than one feature has models.
- [Cached asyncpg engine (`lru_cache`) across function-scoped event loops can break a second integration test] → the single `/health` test builds its own app/engine and disposes it; later integration tests need a fixture that does the same.
- [Coverage threshold fails on the very first run] → measure first and add tests rather than lowering 80%.
- [`workflow_run` runs with the default-branch workflow and secrets context] → it only checks out a commit that already passed CI on `main`, uses no secrets other than `GITHUB_TOKEN`, and never executes PR code.
- [`latest` races if two merges finish CI out of order] → `concurrency` group on CD; the SHA tag is always correct.
- [Build time budget of 5 minutes] → parallel jobs, `uv` cache, buildx `gha` cache.
