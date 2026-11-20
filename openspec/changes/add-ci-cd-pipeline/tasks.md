# Tasks

## 1. Test infrastructure and Alembic metadata

- [x] 1.1 Add `pytest-cov` to the dev dependency group with `uv add --dev pytest-cov` and verify `uv sync --locked` succeeds and `uv run pytest --version` lists the `cov` plugin
- [x] 1.2 In `pyproject.toml` register the `integration` marker, set `addopts = ["-m", "not integration"]`, and add `[tool.coverage.run]` (`branch = true`, `source_pkgs = ["app"]`) and `[tool.coverage.report]` (`fail_under = 80`, `show_missing = true`); verify `uv run pytest --cov` passes, prints branch coverage, and fails when `fail_under` is temporarily raised above the measured value (add unit tests if the measured value is below 80)
- [x] 1.3 Add `Base(DeclarativeBase)` to `src/app/core/db.py` and set `target_metadata = Base.metadata` in `alembic/env.py` (with a comment that new model modules must be imported there); write a unit test for `Base` and verify `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy src` and `uv run pytest` pass
- [x] 1.4 Write `tests/health/test_router_integration.py` marked `integration`: it builds the real app with `Settings` from the environment (no overrides), calls `GET /health` and asserts 200 with `{"status": "ok", "database": "ok"}`, disposing the engine afterwards, and fails (does not skip) if `DATABASE_URL` is missing; verify the default `uv run pytest` deselects it
- [x] 1.5 Verify the integration path locally: start `pgvector/pgvector:pg16` with throwaway credentials, run `uv run alembic upgrade head`, `uv run alembic check` (must succeed with no models), `uv run pytest -m integration` (must pass); then add a throwaway model without a migration and confirm `alembic check` fails, and remove it

## 2. CI workflow

- [x] 2.1 Look up the current major versions of `actions/checkout`, `astral-sh/setup-uv`, `actions/upload-artifact`, `docker/setup-buildx-action` and `docker/build-push-action`, and create `.github/workflows/ci.yml` with triggers (`pull_request`, `push` to `main`), `concurrency` (cancel only for pull requests), top-level `permissions: contents: read`, and the `lint` and `typecheck` jobs (`uv sync --locked`, `ruff check .`, `ruff format --check .`, `mypy src`); verify with `actionlint` (or the YAML parses and every action has a `@vN` tag)
- [x] 2.2 Add the `test` job: `uv run pytest --cov --cov-report=xml`, an `if: always()` step appending `uv run coverage report --format=markdown` to `$GITHUB_STEP_SUMMARY`, and an `if: always()` upload of `coverage.xml`; verify locally that the commands produce `coverage.xml` and a markdown table, and fail when coverage is under the threshold
- [x] 2.3 Add the `integration` job with the `pgvector/pgvector:pg16` service (health-check options, port 5432), job-level `DATABASE_URL` with throwaway credentials, and steps `alembic upgrade head`, `alembic check`, `pytest -m integration`; verify the `services` and `env` blocks match the local run from task 1.5
- [x] 2.4 Add the `docker-build` job (buildx, `push: false`, `cache-from`/`cache-to` of type `gha`); verify `docker build .` succeeds locally
- [x] 2.5 Check `ci.yml` against the spec: job names exactly `lint`, `typecheck`, `test`, `integration`, `docker-build`; no `secrets.` reference; jobs have no `needs:` between them (parallel); verify with `grep -n "secrets\.\|needs:" .github/workflows/ci.yml` showing no matches

## 3. PR rules workflow

- [x] 3.1 Create `commitlint.config.mjs` at the repo root extending `@commitlint/config-conventional` with `type-enum` limited to `feat, fix, docs, refactor, test, chore, ci, build, perf` and `header-max-length` of 72; verify the file is valid JavaScript (`node --check`, if Node is available)
- [x] 3.2 Look up the current majors of `amannn/action-semantic-pull-request` and `wagoid/commitlint-github-action`, and create `.github/workflows/pr-lint.yml` (`pull_request` with `opened, edited, synchronize, reopened`; `permissions` read-only) with a `title` job (semantic-PR action with the nine types, a subject pattern and a clear `subjectPatternError`, plus a shell step that fails titles over 72 characters and prints the format, allowed types and how to edit the title) and a `commits` job (commitlint action with the repo config and a help URL); verify with `actionlint` and by running the length check script against sample titles (72 chars passes, 73 fails)
- [x] 3.3 Verify the commit rules locally with `npx @commitlint/cli` (if Node is available) against sample messages: `feat: add x` passes; `wip stuff` and `feature: x` fail

## 4. CD workflow

- [x] 4.1 Look up the current majors of `docker/login-action` (others from group 2), and create `.github/workflows/cd.yml`: `workflow_run` of `CI` (`completed`, branch `main`), `concurrency` without cancellation, top-level `permissions: contents: read`, a single `publish` job with `if: github.event.workflow_run.conclusion == 'success' && github.event.workflow_run.event == 'push'` and `packages: write` only on that job; it checks out `github.event.workflow_run.head_sha`, lowercases `GITHUB_REPOSITORY`, logs in to `ghcr.io` with `GITHUB_TOKEN`, and pushes `ghcr.io/<repo>:<head_sha>` and `:latest` with the `gha` cache; verify with `actionlint` and that `grep -n "packages: write" .github/workflows/cd.yml` matches only the job-level block
- [x] 4.2 Verify no deploy step exists and no secret other than `GITHUB_TOKEN` is referenced: `grep -rn "secrets\." .github/workflows` lists only `secrets.GITHUB_TOKEN`

## 5. Repository hygiene and docs

- [x] 5.1 Create `.github/dependabot.yml` with weekly updates for `uv` (`/`), `docker` (`/`) and `github-actions` (`/`); verify the YAML parses and lists exactly these three ecosystems
- [x] 5.2 Create `.github/pull_request_template.md` with the short checklist (OpenSpec change linked, tests added/updated, no secrets or personal data, `.claude/CLAUDE.md` rules respected, title is a Conventional Commit); verify the file renders as a markdown checklist
- [x] 5.3 Add the "Commits and PRs" section to `.claude/CLAUDE.md` (Conventional Commits with the allowed types and 72-character limit, small PRs, one OpenSpec change per PR, never push to `main`); verify with `grep -n "Commits and PRs" .claude/CLAUDE.md`
- [x] 5.4 Add the "Repository settings (manual)" section to `README.md` (protect `main`; require PRs and disallow direct pushes; require checks `lint`, `typecheck`, `test`, `integration`, `docker-build` and the PR-rules checks `title` and `commits`; squash merge only with the PR title as the commit message) and update the test instructions to mention `uv run pytest -m integration` and the coverage threshold; verify the section lists every item from the repository-hygiene spec

## 6. Final verification

- [x] 6.1 Run the full local gate: `uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run pytest --cov` all pass, and `actionlint` (if available) passes on all three workflows
- [ ] 6.2 After the repository is pushed to GitHub and the manual settings are applied, open a PR and verify: all five CI jobs and both PR-rules jobs run; a deliberately bad title or commit fails PR rules; a lint error, a mypy error, a failing test, coverage below 80% and a model without migration each fail the matching job (use throwaway branches); after merging to `main`, `ghcr.io/<repo>` has the commit-SHA tag and `latest`
