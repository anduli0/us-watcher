# US-WATCHER backend image (serves API or worker via CMD override).
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

# Dependencies first (better layer caching)
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install -e ".[prod,llm]"

# App code
COPY config ./config
COPY alembic ./alembic
COPY alembic.ini ./
COPY apps/api ./apps/api
COPY apps/worker ./apps/worker

EXPOSE 8000
# API by default; the worker service overrides CMD in docker-compose.
CMD ["python", "-m", "uvicorn", "main:app", "--app-dir", "apps/api", "--host", "0.0.0.0", "--port", "8000"]
