"""Local-disk file storage. Paths stored in the DB are relative to the upload
directory so the whole folder can move to object storage (S3) later without
touching rows."""

import secrets
from pathlib import Path

from fastapi import HTTPException, UploadFile, status

from app.config import get_settings

MAX_FILE_BYTES = 20 * 1024 * 1024  # 20 MB per file
ALLOWED_MIMES = {
    "application/pdf": ".pdf",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}


def upload_root() -> Path:
    root = Path(get_settings().upload_dir)
    root.mkdir(parents=True, exist_ok=True)
    return root


async def save_upload(file: UploadFile) -> tuple[str, str, str]:
    """Persist an uploaded file; returns (relative_path, original_name, mime)."""
    mime = file.content_type or ""
    if mime not in ALLOWED_MIMES:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            "Only PDF, JPEG, PNG and WebP files are accepted",
        )
    data = await file.read()
    if len(data) > MAX_FILE_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Files must be 20 MB or smaller"
        )
    return save_bytes(data, mime, file.filename or "upload")


def save_bytes(data: bytes, mime: str, filename: str) -> tuple[str, str, str]:
    """Persist raw bytes fetched from an external source (e.g. a Google Drive
    attachment) under the same validation and layout as a direct upload.
    Raises ValueError (not HTTPException) since callers may be background
    jobs rather than requests."""
    if mime not in ALLOWED_MIMES:
        raise ValueError(f"Unsupported file type: {mime}")
    if len(data) > MAX_FILE_BYTES:
        raise ValueError("File exceeds the 20 MB limit")
    rel_path = f"{secrets.token_hex(16)}{ALLOWED_MIMES[mime]}"
    (upload_root() / rel_path).write_bytes(data)
    return rel_path, filename, mime


def read_file(rel_path: str) -> bytes:
    return (upload_root() / rel_path).read_bytes()


def absolute_path(rel_path: str) -> Path:
    return upload_root() / rel_path
