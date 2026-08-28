FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml ./
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./
COPY seed ./seed

RUN pip install --no-cache-dir .

EXPOSE 8000

# Run migrations, then start the API. The API also runs the job worker in-process
# by default (RUN_WORKER_IN_API), which is the deployment today.
#
# Task 1.3 (AV-82) also makes the worker runnable on its own from this same
# image, by overriding the command:
#
#   python -m app.workers
#
# A worker service must NOT run `alembic upgrade head` — two services racing the
# same migration on deploy is how you get a half-applied schema. The API owns
# migrations; the worker assumes they have already run.
#
# Splitting them is a deliberate cutover, not a default: an API with
# RUN_WORKER_IN_API=false and no worker service running means marking,
# extraction, readiness and reports all stop with no error anywhere. Deployment
# stays single-instance until Phase 11 (AV-85).
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
