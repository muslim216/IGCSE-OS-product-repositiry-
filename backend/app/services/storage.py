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
# rather than accepted here and failed later.
CONVERT_TO_JPEG = {"image/heic", "image/heif", "image/heic-sequence"}

# Some clients (and Google Drive) report these instead of the canonical type.
MIME_ALIASES = {
    "image/jpg": "image/jpeg",
    "image/pjpeg": "image/jpeg",
    "image/x-png": "image/png",
}


def _to_jpeg(data: bytes) -> bytes:
    """Transcode a HEIC/HEIF image to JPEG. Decoding doubles as validation —
    bytes that merely claim to be HEIC fail here rather than getting stored."""
    import pillow_heif
    from PIL import Image

    pillow_heif.register_heif_opener()
    with Image.open(io.BytesIO(data)) as img:
        buffer = io.BytesIO()
        img.convert("RGB").save(buffer, format="JPEG", quality=90)
        return buffer.getvalue()


def _normalize(data: bytes, mime: str) -> tuple[bytes, str]:
    """Resolve mime aliases and transcode HEIC to JPEG.

    Raises ValueError when a claimed HEIC photo can't actually be decoded.
    """
    mime = MIME_ALIASES.get(mime, mime)
    if mime in CONVERT_TO_JPEG:
        try:
            data = _to_jpeg(data)
        except Exception:
            raise ValueError(
                "That photo couldn't be read. Try saving it as JPEG and uploading again."
            ) from None
        mime = "image/jpeg"
    return data, mime


def _looks_like_webp(data: bytes) -> bool:
    # RIFF container: "RIFF" <4-byte size> "WEBP".
    return data[:4] == b"RIFF" and data[8:12] == b"WEBP"


#: Leading bytes each accepted format must actually start with. The declared
#: Content-Type comes from the client and is trivially forged, so it decides
#: nothing on its own — a .exe announced as image/png would otherwise be stored
#: and handed back under that type. Files are served as attachments with
#: server-generated names, so this is defence in depth rather than the only
#: thing standing between a bad upload and a browser.
_MAGIC: dict[str, tuple[bytes, ...]] = {
    "application/pdf": (b"%PDF",),
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
}


def content_matches_mime(data: bytes, mime: str) -> bool:
    if mime == "image/webp":
        return _looks_like_webp(data)
    return any(data.startswith(prefix) for prefix in _MAGIC.get(mime, ()))


def upload_root() -> Path:
    root = Path(get_settings().upload_dir)
    root.mkdir(parents=True, exist_ok=True)
    return root


async def save_upload(file: UploadFile) -> tuple[str, str, str]:
    """Persist an uploaded file; returns (relative_path, original_name, mime)."""
    mime = MIME_ALIASES.get(file.content_type or "", file.content_type or "")
    if mime not in ALLOWED_MIMES and mime not in CONVERT_TO_JPEG:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            "Only PDF, JPEG, PNG, WebP and iPhone (HEIC) files are accepted",
        )
    data = await file.read()
    if len(data) > MAX_FILE_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Files must be 20 MB or smaller"
        )
    try:
        data, mime = _normalize(data, mime)
    except ValueError as exc:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, str(exc)) from None
    if not content_matches_mime(data, mime):
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            "This file's contents don't match its type — re-export it as a PDF or image "
            "and try again",
        )
    return _write(data, mime, file.filename or "upload")


def save_bytes(data: bytes, mime: str, filename: str) -> tuple[str, str, str]:
    """Persist raw bytes fetched from an external source (e.g. a Google Drive
    attachment) under the same validation and layout as a direct upload.
    Raises ValueError (not HTTPException) since callers may be background
    jobs rather than requests."""
    # Cap the *source* bytes before _normalize, which may decode and re-encode
    # a HEIC. Checking only afterwards would both let an arbitrarily large photo
    # through the decoder and measure the (smaller) transcoded JPEG instead.
    if len(data) > MAX_FILE_BYTES:
        raise ValueError("File exceeds the 20 MB limit")
    data, mime = _normalize(data, mime)
    if mime not in ALLOWED_MIMES:
        raise ValueError(f"Unsupported file type: {mime}")
    if len(data) > MAX_FILE_BYTES:
        raise ValueError("File exceeds the 20 MB limit")
    if not content_matches_mime(data, mime):
        raise ValueError(f"File contents do not match the declared type: {mime}")
    return _write(data, mime, filename)


def _write(data: bytes, mime: str, filename: str) -> tuple[str, str, str]:
    rel_path = f"{secrets.token_hex(16)}{ALLOWED_MIMES[mime]}"
    (upload_root() / rel_path).write_bytes(data)
    return rel_path, filename, mime


def delete_file(rel_path: str) -> None:
    """Remove a stored file, tolerating one that is already gone.

    Used to undo writes when a later step in the same request fails — a file on
    disk with no row pointing at it is invisible and can never be cleaned up.
    """
    (upload_root() / rel_path).unlink(missing_ok=True)


def read_file(rel_path: str) -> bytes:
    return (upload_root() / rel_path).read_bytes()


def absolute_path(rel_path: str) -> Path:
    return upload_root() / rel_path
