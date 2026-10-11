FROM python:3.11-slim

WORKDIR /app

# Dependencies come from the lock, not from the ranges in pyproject.toml. With
# only ranges, every image build (Render builds one on each merge) installed
# whatever each library had released that day, so production could change
# behaviour with no change in the repo. --require-hashes makes pip refuse any
# file the lock does not name. Regenerate it with the command in its header.
# Copied before the application code so this layer is cached until the lock
# itself changes.
COPY pyproject.toml requirements.lock ./
RUN pip install --no-cache-dir --require-hashes -r requirements.lock

COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./
COPY seed ./seed

# The app itself only; --no-deps because resolving anything here would undo the lock.
RUN pip install --no-cache-dir --no-deps .

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
