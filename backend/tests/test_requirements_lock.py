"""The lock files must stay in step with `pyproject.toml`.

The Dockerfile installs requirements.lock (plus requirements-build.lock) with
`--require-hashes` and then the app with `--no-deps`. That is what keeps a
library release from changing production, and it fails open in one way: add or
raise a dependency in pyproject.toml, forget the lock, and the image builds
without the new package (or with the old version) — the app then fails at import
in production, or worse, runs on a version nobody chose. This is the offline
check for that drift. Two other checks cover what it cannot: CI's image-build job
proves the locks install in the real base image, and `scripts/check_locks_current`
regenerates each lock and compares it byte for byte (a changed extra or a new
transitive package is invisible to a test that reads only names and specifiers).

Every failure message ends with the commands that fix it.
"""

import tomllib

import pytest
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

from scripts.lockfile import (
    BACKEND,
    BUILD_LOCK,
    DEV_LOCK,
    RUNTIME_LOCK,
    parse_lock,
    regenerate_hint,
    versions,
)

PYPROJECT = BACKEND / "pyproject.toml"
DEV_TOOLS = {"pytest", "pytest-asyncio", "ruff", "mypy"}


def _project() -> dict:
    return tomllib.loads(PYPROJECT.read_text())


def _runtime_requirements() -> list[Requirement]:
    return [Requirement(line) for line in _project()["project"]["dependencies"]]


def _fail(problems: list[str]) -> None:
    assert not problems, "\n".join(problems) + "\n\n" + regenerate_hint()


def test_every_runtime_dependency_is_pinned_at_an_allowed_version():
    locked = versions(RUNTIME_LOCK)
    problems = []
    for req in _runtime_requirements():
        name = canonicalize_name(req.name)
        if name not in locked:
            problems.append(f"{req.name}: declared in pyproject.toml but not pinned in the lock")
        elif not req.specifier.contains(locked[name], prereleases=True):
            problems.append(
                f"{req.name}: locked at {locked[name]} which does not satisfy '{req.specifier}'"
            )
    _fail(problems)


def test_every_pin_in_every_lock_carries_hashes():
    # `pip install --require-hashes` rejects an unhashed line, but only on the
    # image build; catching it here keeps the failure on the pull request.
    problems = []
    for path in (RUNTIME_LOCK, BUILD_LOCK, DEV_LOCK):
        pins = parse_lock(path)
        if not pins:
            problems.append(f"{path.name}: no pins found")
        problems += [f"{path.name}: {p.name} has no hashes" for p in pins if not p.hashes]
    _fail(problems)


def test_the_runtime_lock_has_no_dev_tools():
    # The image installs this file; locking pytest or ruff here would ship them.
    leaked = DEV_TOOLS & set(versions(RUNTIME_LOCK))
    _fail([f"dev tools leaked into requirements.lock: {sorted(leaked)}"] if leaked else [])


def test_the_dev_lock_holds_the_dev_tools_and_agrees_with_the_runtime_lock():
    # One package at two versions across the files would mean CI tests something
    # production does not run.
    runtime, dev = versions(RUNTIME_LOCK), versions(DEV_LOCK)
    problems = [
        f"dev extra '{n}' is not in requirements-dev.lock" for n in sorted(DEV_TOOLS - set(dev))
    ]
    problems += [
        f"{name}: {version} in requirements.lock but {dev.get(name)} in requirements-dev.lock"
        for name, version in runtime.items()
        if dev.get(name) != version
    ]
    for req in (
        Requirement(line) for line in _project()["project"]["optional-dependencies"]["dev"]
    ):
        name = canonicalize_name(req.name)
        if name in dev and not req.specifier.contains(dev[name], prereleases=True):
            problems.append(
                f"{req.name}: locked at {dev[name]}, does not satisfy '{req.specifier}'"
            )
    _fail(problems)


@pytest.mark.parametrize("requirement", _project()["build-system"]["requires"])
def test_the_build_backend_is_pinned_at_an_allowed_version(requirement):
    # The app is installed with --no-build-isolation, so the build backend named
    # in pyproject.toml must come from a lock instead of being downloaded unpinned.
    req = Requirement(requirement)
    locked = versions(BUILD_LOCK)
    name = canonicalize_name(req.name)
    problems = []
    if name not in locked:
        problems.append(f"{req.name}: [build-system].requires but not in requirements-build.lock")
    elif not req.specifier.contains(locked[name], prereleases=True):
        problems.append(f"{req.name}: locked at {locked[name]}, does not satisfy '{req.specifier}'")
    _fail(problems)


def test_the_build_lock_input_matches_pyproject():
    # requirements-build.in repeats [build-system].requires (uv cannot read it
    # from there); this keeps the copy honest.
    lines = [
        line.strip()
        for line in (BACKEND / "requirements-build.in").read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    _fail(
        []
        if sorted(lines) == sorted(_project()["build-system"]["requires"])
        else [
            f"requirements-build.in {lines} differs from [build-system].requires "
            f"{_project()['build-system']['requires']}"
        ]
    )
