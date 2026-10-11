"""`requirements.lock` must pin every runtime dependency in `pyproject.toml`.

The Dockerfile installs from the lock with `--require-hashes` and then installs
the app with `--no-deps`. That is what keeps a library release from changing
production, and it fails open in one way: add or raise a dependency in
pyproject.toml, forget the lock, and the image builds without the new package
(or with the old version) — the app then fails at import in production, or
worse, runs on a version nobody chose. This test is the offline check for that
drift; the image-build job in CI is the check that the lock installs at all.

The fix for a failure is one command, in the lock's own header:

    uv pip compile pyproject.toml --universal --python-version 3.11 \
        --generate-hashes --no-annotate -o requirements.lock

Re-running it keeps every version already pinned, so it only adds or moves what
pyproject.toml now demands. Add --upgrade-package NAME to move one on purpose.
"""

import pathlib
import re
import tomllib

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version

BACKEND = pathlib.Path(__file__).resolve().parent.parent
LOCK = BACKEND / "requirements.lock"
PYPROJECT = BACKEND / "pyproject.toml"

# `name==1.2.3 \` at the start of a line; the hash and comment lines are indented
# or begin with `#`, so anchoring at column 0 skips them.
PIN = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==(\S+?)\s*(?:\\|;|$)", re.MULTILINE)


def _locked() -> dict[str, Version]:
    return {
        canonicalize_name(name): Version(version) for name, version in PIN.findall(LOCK.read_text())
    }


def _runtime_requirements() -> list[Requirement]:
    data = tomllib.loads(PYPROJECT.read_text())
    return [Requirement(line) for line in data["project"]["dependencies"]]


def test_every_runtime_dependency_is_pinned_at_an_allowed_version():
    locked = _locked()
    problems = []
    for req in _runtime_requirements():
        name = canonicalize_name(req.name)
        if name not in locked:
            problems.append(f"{req.name}: declared in pyproject.toml but not pinned in the lock")
        elif not req.specifier.contains(locked[name], prereleases=True):
            problems.append(
                f"{req.name}: locked at {locked[name]} which does not satisfy '{req.specifier}'"
            )
    assert not problems, "requirements.lock is out of step with pyproject.toml:\n" + "\n".join(
        problems
    )


def test_every_pin_carries_hashes():
    # `pip install --require-hashes` rejects an unhashed line, but only on the
    # image build; catching it here keeps the failure on the pull request.
    text = LOCK.read_text()
    blocks = re.split(r"(?m)^(?=[A-Za-z0-9])", text)[1:]
    assert blocks, "no pins found in requirements.lock"
    unhashed = [b.split("==")[0] for b in blocks if "--hash=sha256:" not in b]
    assert not unhashed, f"pins without a hash: {unhashed}"


def test_dev_tools_are_not_in_the_lock():
    # The lock is the runtime set. Locking pytest or ruff would ship them in the
    # production image and make the dev extra look pinned when it is not.
    locked = _locked()
    dev = {"pytest", "pytest-asyncio", "ruff", "mypy"}
    assert not (dev & set(locked)), f"dev tools leaked into the lock: {dev & set(locked)}"
