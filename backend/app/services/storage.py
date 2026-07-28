"""Local-disk file storage. Paths stored in the DB are relative to the upload
directory so the whole folder can move to object storage (S3) later without
touching rows."""

import io
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

# iPhones photograph in HEIC by default, which is most of what students upload.
# The marking pipeline passes the stored mime straight to the Anthropic image
# API, which doesn't accept HEIC — so these are transcoded to JPEG on the way in
# rather than accepted and failed later.
CONVERT_TO_JPEG = {"image/heic", "image/heif", "image/heic-sequence"}

# Some clients (and Google Drive) report these instead of the canonical type.
MIME_ALIASES = {
    "image/jpg": "image/jpeg",
    "image/pjpeg": "image/jpeg",
    "image/x-png": "image/png",
}


def upload_root() -> Path:
    root = Path(get_settings().upload_dir)
    root.mkdir(parents=True, exist_ok=True)
    return root


def _to_jpeg(data: bytes) -> bytes:
    """Transcode a HEIC/HEIF image to JPEG."""
    import pillow_heif
    from PIL import Image

    pillow_heif.register_heif_opener()
    with Image.open(io.BytesIO(data)) as img:
        buffer = io.BytesIO()
        img.convert("RGB").save(buffer, format="JPEG", quality=90)
        return buffer.getvalue()


def save_bytes(data: bytes, mime: str, name: str) -> tuple[str, str, str]:
    """Persist raw bytes; returns (relative_path, original_name, stored_mime).

    The single write path for the app — everything that stores a file goes
    through here so the allowlist, size cap and naming scheme can't drift.
    """
    mime = MIME_ALIASES.get(mime, mime)

    if mime in CONVERT_TO_JPEG:
        try:
            data = _to_jpeg(data)
        except Exception:
            raise HTTPException(
                status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                "That photo couldn't be read. Try saving it as JPEG and uploading again.",
            ) from None
        mime = "image/jpeg"

    if mime not in ALLOWED_MIMES:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            "Only PDF, JPEG, PNG, WebP and iPhone (HEIC) files are accepted",
        )
    if len(data) > MAX_FILE_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Files must be 20 MB or smaller"
        )

    rel_path = f"{secrets.token_hex(16)}{ALLOWED_MIMES[mime]}"
    (upload_root() / rel_path).write_bytes(data)
    return rel_path, name, mime


async def save_upload(file: UploadFile) -> tuple[str, str, str]:
    """Persist an uploaded file; returns (relative_path, original_name, mime)."""
    data = await file.read()
    fallback = file.filename or "upload"
    return save_bytes(data, file.content_type or "", fallback)


def read_file(rel_path: str) -> bytes:
    return (upload_root() / rel_path).read_bytes()


def absolute_path(rel_path: str) -> Path:
    return upload_root() / rel_path
