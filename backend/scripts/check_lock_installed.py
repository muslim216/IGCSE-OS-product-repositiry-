"""Fail if the environment is not running exactly the versions in requirements.lock.

CI installs the lock first and the project with its `dev` extra second, so the
suite exercises the versions that ship. The second install is a plain
`pip install -e ".[dev]"`: pip leaves an already-satisfied package alone, but
nothing guarantees it — a dev tool whose own requirement wants a newer
`packaging`, or a pyproject.toml range edited without the lock, would move a
locked package and the suite would quietly stop testing what production runs.
This is the check for that: every pin in the lock must be installed at exactly
that version.

Usage (from backend/): python -m scripts.check_lock_installed
"""

import pathlib
import re
import sys
from importlib import metadata

from packaging.requirements import Requirement

LOCK = pathlib.Path(__file__).resolve().parent.parent / "requirements.lock"
# The lock is universal, so some pins carry an environment marker
# (`async-timeout==5.0.1 ; python_full_version < '3.11.3'`). Those only have to
# be installed where the marker holds.
PIN = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*==[^\\\n]+?)\s*\\?$", re.MULTILINE)


def main() -> int:
    pins = [Requirement(line) for line in PIN.findall(LOCK.read_text())]
    if not pins:
        print("no pins found in requirements.lock", file=sys.stderr)
        return 1
    problems = []
    for req in pins:
        if req.marker is not None and not req.marker.evaluate():
            continue
        name = req.name
        wanted = next(iter(req.specifier)).version
        try:
            installed = metadata.version(name)
        except metadata.PackageNotFoundError:
            problems.append(f"{name}: locked at {wanted}, not installed")
            continue
        if installed != wanted:
            problems.append(f"{name}: locked at {wanted}, installed {installed}")
    if problems:
        print("environment disagrees with requirements.lock:", file=sys.stderr)
        for line in problems:
            print(f"  {line}", file=sys.stderr)
        return 1
    print(f"{len(pins)} locked packages installed at their locked versions")
    return 0


if __name__ == "__main__":
    sys.exit(main())
