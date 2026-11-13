# Dependabot bumps this digest.
FROM python:3.11-slim@sha256:0a236bf8f0b6013383df04d1cd02cb0abe5fbfa1a7012141d7ff9202b7cb30a6

WORKDIR /app

# Dependencies come from the locks, not from the ranges in pyproject.toml. With
# only ranges, every image build (Render builds one on each merge) installed
# whatever each library had released that day, so production could change
# behaviour with no change in the repo. --require-hashes makes pip refuse any
# file the locks do not name, and --only-binary :all: stops it falling back to
# building a source distribution, which would run that package's setup script.
# requirements-build.lock is the build backend (setuptools): the app is installed
# below with --no-build-isolation, which would otherwise download an unpinned
# one into a throwaway environment and run it. Regenerate the locks with the
# command in each file's header. Only the lock files are copied first, so this
# layer is cached until a lock changes and an edit to tool config in
# pyproject.toml does not rebuild it.
COPY requirements.lock requirements-build.lock ./
RUN pip install --no-cache-dir --require-hashes --only-binary :all: \
    -r requirements.lock -r requirements-build.lock

COPY pyproject.toml ./
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./
COPY seed ./seed

# The app itself only: --no-deps because resolving anything here would undo the
# locks, --no-build-isolation so the build uses the locked setuptools above.
#
# Then the account an uploaded PDF is read under (app/services/pdf_child.py).
# The API still runs as root here, so the child drops to this account before it
# reads anything: no home, no shell, owning nothing, and unable to reach the
# API process or anything only root can read. T-009, which gives the API an
# account of its own, must keep this one separate from it. No USER line for the
# app is set here. One RUN for both, so the image has one layer fewer.
RUN pip install --no-cache-dir --no-deps --no-build-isolation --only-binary :all: . \
    && groupadd --system pdfsandbox \
    && useradd --system --gid pdfsandbox --no-create-home --home-dir /nonexistent \
        --shell /usr/sbin/nologin pdfsandbox

EXPOSE 8000

# Run migrations, then start the API. The API also runs the job worker in-process
# by default (RUN_WORKER_IN_API), which is the deployment today.
#
# On Render, migrations now run first in render.yaml's preDeployCommand, where a
# failure cancels the deploy instead of taking the API down (T-052). The run here
# is a backstop: a no-op after a good pre-deploy, and it heals a deploy where the
# pre-deploy did not run (the field cleared in the dashboard, pipeline minutes
# exhausted). Keep it. It is also why a dashboard rollback across a migration
# takes the API down: the older image cannot find the newer revision and never
# reaches uvicorn. Roll forward with a revert instead.
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
