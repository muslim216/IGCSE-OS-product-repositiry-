"""Fail if a lock file is not what its own header command produces today.

tests/test_requirements_lock.py compares names and version specifiers, which
catches a forgotten dependency but not a changed extra (`uvicorn[standard]`
pulling in `uvloop`) or a new transitive package — those would first show up as
a cryptic pip error in the image build. This regenerates every lock into a
temporary file with the exact command recorded in its header and compares it
with the committed one. The commands carry `--exclude-newer`, so nothing
published later can change the answer: a difference always means pyproject.toml
and the lock disagree, never that PyPI moved.

The regeneration is from scratch (the temporary output does not exist, so uv has
no earlier pins to prefer), which is why the fix below starts with `rm`.

Usage (from backend/): python -m scripts.check_locks_current
"""

import difflib
import pathlib
import shlex
import subprocess
import sys
import tempfile

from scripts.lockfile import ALL_LOCKS, BACKEND, header_command, regenerate_hint

PREFIX = ["uv", "pip", "compile"]


def regenerate(path: pathlib.Path, scratch: pathlib.Path) -> str:
    command = header_command(path)
    argv = shlex.split(command)
    if argv[:3] != PREFIX or "-o" not in argv:
        raise ValueError(f"{path.name}: header command is not a `uv pip compile ... -o` line")
    out = scratch / path.name
    argv[argv.index("-o") + 1] = str(out)
    # Keep the header text identical to the committed one (which names the real
    # output file, not this temporary path).
    argv += ["--custom-compile-command", command]
    # The module form, so the uv that pip installed from the dev lock is the one
    # that runs, whatever happens to be first on PATH.
    result = subprocess.run(
        [sys.executable, "-m", "uv", *argv[1:]],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"{path.name}: uv failed:\n{result.stderr[-2000:]}")
    return out.read_text()


def _without_hashes(text: str) -> list[str]:
    # A changed pin is readable as one line; its dozens of hash lines are noise.
    return [line for line in text.splitlines() if not line.lstrip().startswith("--hash=")]


def main() -> int:
    failures = []
    with tempfile.TemporaryDirectory() as tmp:
        scratch = pathlib.Path(tmp)
        for path in ALL_LOCKS:
            try:
                fresh = regenerate(path, scratch)
            except (ValueError, RuntimeError) as exc:
                failures.append(str(exc))
                continue
            committed = path.read_text()
            if fresh != committed:
                diff = list(
                    difflib.unified_diff(
                        _without_hashes(committed),
                        _without_hashes(fresh),
                        f"committed {path.name}",
                        f"regenerated {path.name}",
                        lineterm="",
                        n=0,
                    )
                )
                shown = "\n".join(diff[:40]) or "(only the hashes differ)"
                more = f"\n... {len(diff) - 40} more lines" if len(diff) > 40 else ""
                failures.append(
                    f"{path.name} is not what its header command produces:\n{shown}{more}"
                )
    if failures:
        print("\n\n".join(failures), file=sys.stderr)
        print(
            "\npyproject.toml (or requirements-build.in) changed without the lock files "
            "being regenerated.\n" + regenerate_hint(),
            file=sys.stderr,
        )
        return 1
    print(f"{len(ALL_LOCKS)} lock files match their header commands")
    return 0


if __name__ == "__main__":
    sys.exit(main())
