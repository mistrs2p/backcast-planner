# API image (TASK-117) — the FastAPI backend as a production
# container. Multi-stage: the builder compiles the package into an
# isolated venv, the runtime ships only that venv and the source —
# no build toolchain, no caches, no tests.
#
# The app runs as a non-root user; the container's HEALTHCHECK hits
# the /health endpoint (docs/14's pipeline: deploy → smoke test →
# health check — the health check travels with the image).
# Persistence is still in-memory (the PostgreSQL repositories are
# the migration pipeline's task, TASK-119): a container restart
# starts a clean slate, and the compose file says so honestly.

# syntax=docker/dockerfile:1
FROM python:3.12-slim AS builder
WORKDIR /build
COPY pyproject.toml ./
COPY src/ ./src/
RUN python -m venv /venv \
    && /venv/bin/pip install --no-cache-dir .

FROM python:3.12-slim AS runtime
WORKDIR /app
RUN groupadd --system app && useradd --system --gid app app
COPY --from=builder --chown=app:app /venv /venv
COPY --chown=app:app src/ ./src/
ENV PATH="/venv/bin:$PATH"
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health').status == 200 else 1)"
CMD ["uvicorn", "backcasting.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
