FROM python:3.12-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.13.6 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
# Optional extras, e.g. --build-arg EXTRAS="--extra local-embeddings" (pulls torch: several GB).
ARG EXTRAS=""

# Dependencies first (better layer caching), without the project itself.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project $EXTRAS

# Then the project, installed non-editable so src/ is not needed at runtime.
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable $EXTRAS


FROM python:3.12-slim AS final
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
RUN groupadd --system --gid 10001 app && useradd --system --uid 10001 --gid app --no-create-home app
# Uploaded resumes live here: a named volume mounted on it inherits this ownership.
RUN mkdir -p /data/resumes && chown app:app /data/resumes
WORKDIR /app
COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY --chown=app:app alembic.ini ./
COPY --chown=app:app alembic ./alembic
USER app
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
