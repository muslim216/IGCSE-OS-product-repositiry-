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

LOCK = pathlib.Path(__file__).resolve().parent.parent / "requirements.lock"
PIN = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==(\S+?)\s*(?:\\|;|$)", re.MULTILINE)


def main() -> int:
    pins = PIN.findall(LOCK.read_text())
    if not pins:
        print("no pins found in requirements.lock", file=sys.stderr)
        return 1
    problems = []
    for name, wanted in pins:
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
