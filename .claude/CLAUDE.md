# ATS Resume Analyzer

AI agent that compares a developer's resume + profile against a job position and reports what is missing to pass AI/ATS first-step screening.
Backend only: Python 3.12, FastAPI, PostgreSQL + pgvector.

## Workflow (OpenSpec)
- Specs live in `openspec/`. Read the relevant spec/change before writing code.
- Do not implement anything that is not covered by a spec. If it is missing, propose a change first.
- Work in small tasks. One task = code + tests. Stop and report when a task is done.
- If a requirement is ambiguous, ask. Do not guess.

## Commands (always use `uv`, never bare `pip`)
- Run API: `uv run uvicorn app.main:app --reload`
- Tests: `uv run pytest`
- Lint + format: `uv run ruff check . --fix && uv run ruff format .`
- Types: `uv run mypy src`
- Migrations: `uv run alembic revision --autogenerate -m "msg"` then `uv run alembic upgrade head`
- Evals: `uv run python -m evals.run`
- Before saying a task is done, tests, ruff and mypy must all pass.

## Folder structure (package by feature, not by type)
```
src/app/
  main.py          # creates the app and includes routers. No logic here.
  core/            # config.py (pydantic-settings), db.py, logging.py, errors.py
  resumes/         # one folder per feature: resumes, jobs, profile, analyses
    router.py      # HTTP only (like a Controller)
    schemas.py     # Pydantic request/response models (like DTOs)
    models.py      # SQLAlchemy models (like Entities)
    repository.py  # DB access only
    service.py     # business logic
  ai/
    llm.py         # the ONLY place that calls the LLM provider
    embeddings.py  # the ONLY place that creates embeddings
    parsing/       # PDF/DOCX -> clean text
    extraction/    # text -> structured Resume / Job (Pydantic)
    matching/      # deterministic checks + semantic (vector) matching
    pipeline.py    # orchestrates the analysis steps
    prompts/       # prompts as versioned .md files, never inline strings
tests/             # mirrors src/app
evals/             # dataset of resume/job pairs + runner
alembic/           # migrations
```

## Architecture rules
- Flow is always: router -> service -> repository. Routers never touch the DB. Repositories never contain business rules.
- Pipeline steps are small, pure functions that take and return Pydantic models. Easy to test, easy to swap.
- Everything the LLM returns is parsed into a Pydantic model. Invalid output = retry or a typed error, never a raw string passed on.
- Use dependency injection (`Depends`) for DB session, settings, LLM client. No global state, no singletons created at import time.
- Async everywhere in the request path (SQLAlchemy 2.0 async + asyncpg). CPU-heavy work (PDF parsing) runs in a threadpool.
- Config only from environment via `pydantic-settings`. Provide `.env.example`.

## ALWAYS
- Type hints on every function. Code must pass `mypy` strict.
- Use SQLAlchemy 2.0 style (`select()`), Pydantic v2, and Alembic for every schema change.
- Raise custom domain exceptions in services; map them to HTTP responses in one place (`core/errors.py`).
- Use `logging`, structured and without resume content.
- Require evidence for every "requirement met" verdict: a quote from the resume. No quote = "missing".
- Use temperature 0 for judging/extraction steps.
- Mock the LLM and embeddings in unit tests. Quality of AI output is checked in `evals/`, not in unit tests.
- Validate uploads: file type (PDF/DOCX), max size, and non-empty extracted text.
- Support Portuguese and English resumes/jobs (use multilingual embeddings).
- Write the test first or together with the code, never after.

## NEVER
- Never fabricate or "embellish" resume content. Rewrite suggestions may only use facts from the resume or the user profile.
- Never log, print or commit resume text, personal data, API keys or `.env`.
- Never call the LLM or embeddings provider outside `ai/llm.py` / `ai/embeddings.py`.
- Never write prompts as inline strings in code.
- Never put business logic in routers or DB queries in services.
- Never use `print`, bare `except:`, mutable default arguments, or `from x import *`.
- Never make real network/LLM calls in tests.
- Never edit an applied Alembic migration; create a new one.
- Never add a dependency or a framework (e.g. LangChain) without asking first.
- Never change the folder structure above without asking first.
## Commits and PRs
- Use Conventional Commits for every commit message and PR title: `<type>: <short description>`. Allowed types: `feat, fix, docs, refactor, test, chore, ci, build, perf`. Max 72 characters on the first line/title.
- Keep PRs small. One OpenSpec change per PR.
- Never push to `main`; always open a PR. CI (`lint`, `typecheck`, `test`, `integration`, `docker-build`) and the PR rules (`title`, `commits`) must pass.
