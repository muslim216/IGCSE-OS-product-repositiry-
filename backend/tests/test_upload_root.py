"""T-027: the account PDFs are read under cannot reach the stored uploads.

The PDF child drops to its own account (`services/pdf_child.py`). Files the API
writes are world-readable by default, so the upload root itself is closed to
everyone but its owner: an account that cannot enter the directory cannot read
anything under it, including files written before this change.
"""

import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from app.config import get_settings
from app.services import storage


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_the_local_backend_closes_the_upload_root(tmp_path, monkeypatch):
    root = tmp_path / "uploads"
    root.mkdir(mode=0o755)
    (root / "old.pdf").write_bytes(b"%PDF-1.4 written before the change")
    monkeypatch.setattr(get_settings(), "upload_dir", str(root))

    storage.LocalBackend()

    assert _mode(root) == 0o700


def test_a_missing_upload_root_is_created_closed(tmp_path, monkeypatch):
    root = tmp_path / "not-yet" / "uploads"
    monkeypatch.setattr(get_settings(), "upload_dir", str(root))

    storage.LocalBackend()

    assert root.is_dir()
    assert _mode(root) == 0o700


@pytest.mark.skipif(
    not (sys.platform.startswith("linux") and os.geteuid() == 0),
    reason="needs root on Linux to run as another account; the CI image step checks it there",
)
def test_another_account_cannot_read_a_stored_upload(tmp_path, monkeypatch):
    tmp_path.chmod(0o755)
    root = tmp_path / "uploads"
    monkeypatch.setattr(get_settings(), "upload_dir", str(root))
    storage.LocalBackend()
    stored = root / "org" / "1" / "paper.pdf"
    stored.parent.mkdir(parents=True)
    stored.write_bytes(b"%PDF-1.4 a tutor's file")
    stored.chmod(0o644)

    done = subprocess.run(
        [sys.executable, "-I", "-c", f"open({str(stored)!r}, 'rb').read()"],
        user="nobody",
        group="nogroup" if _group_exists("nogroup") else "nobody",
        extra_groups=[],
        capture_output=True,
        check=False,
    )
    assert done.returncode != 0
    assert b"PermissionError" in done.stderr


def _group_exists(name: str) -> bool:
    import grp

    try:
        grp.getgrnam(name)
    except KeyError:
        return False
    return True
