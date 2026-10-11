"""Fail if the environment is not running exactly the versions in the lock files.

CI installs requirements-dev.lock (the runtime set plus pytest, ruff, mypy, uv)
and requirements-build.lock, then the project with --no-deps, so the suite
exercises the versions that ship. Nothing in that sequence resolves, so nothing
should move a locked package — but the migrations job also installs moto, which
is deliberately left unlocked, and a step that "should" be harmless is exactly
what needs a check. This is it: every pin in each lock file must be installed at
exactly that version (pins whose environment marker is false here, such as
`async-timeout` on a new enough Python, are skipped and not counted).

Usage (from backend/): python -m scripts.check_lock_installed [LOCKFILE ...]
With no arguments it checks all of them.
"""

import pathlib
import sys
from importlib import metadata

from scripts.lockfile import ALL_LOCKS, parse_lock, regenerate_hint


def find_problems(paths: list[pathlib.Path]) -> tuple[set[str], list[str]]:
    """The distinct package names checked, and a line for every disagreement."""
    checked: set[str] = set()
    problems: list[str] = []
    for path in paths:
        for pin in parse_lock(path):
            if not pin.applies_here():
                continue
            checked.add(pin.name)  # the dev lock repeats every runtime pin
            installed = _installed_version(pin.name)
            if installed is None:
                problems.append(f"{path.name}: {pin.name} locked at {pin.version}, not installed")
            elif installed != str(pin.version):
                problems.append(
                    f"{path.name}: {pin.name} locked at {pin.version}, installed {installed}"
                )
    return checked, problems


def _installed_version(name: str) -> str | None:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


def main(argv: list[str]) -> int:
    paths = [pathlib.Path(a) for a in argv] or list(ALL_LOCKS)
    checked, problems = find_problems(paths)
    if not checked:
        print("no pins found in the lock files", file=sys.stderr)
        return 1
    if problems:
        print("environment disagrees with the lock files:", file=sys.stderr)
        for line in problems:
            print(f"  {line}", file=sys.stderr)
        print(
            "\nIf a package was installed outside the locks, reinstall from them:\n"
            "  pip install --require-hashes --only-binary :all: "
            "-r requirements-dev.lock -r requirements-build.lock\n"
            "If a lock file itself is stale (pyproject.toml changed), regenerate it.\n"
            + regenerate_hint(),
            file=sys.stderr,
        )
        return 1
    print(f"{len(checked)} distinct locked packages installed at their locked versions")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
