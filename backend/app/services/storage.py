"""File storage behind a backend-agnostic interface.

Uploads are validated here and persisted through a `StorageBackend` — local disk
in development and tests, S3-compatible object storage in production. The
database stores object *keys*, never bytes and never absolute paths, so the same
row resolves whichever backend is configured.

Keys are tenant-scoped (`org/{organization_id}/{random}.ext`), server-generated,
and contain no user-controlled fragment (`SEC-16`). Rows written before task 1.2
hold a bare `{random}.ext` key and still *resolve* under either backend: the key
is whatever the row says, so no key rewrite or migration is needed.

That is about key resolution only, and is not the same as the data being there.
Switching an existing deployment from local disk to S3 does not move any bytes —
every pre-existing file has to be copied into the bucket under its stored key, or
those rows resolve to objects that do not exist. That copy is part of the
production cutover, which is deliberately a separate change from this one;
`STORAGE_BACKEND` stays `local` until it happens.
"""

import asyncio
import io
import secrets
from functools import lru_cache
from pathlib import Path
from typing import Protocol
from urllib.parse import quote

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
    bytes that merely claim to be HEIC fail here rather than getting stored.

    Called only via `asyncio.to_thread`: decode-and-re-encode is CPU-bound and
    ran on the event loop until task 1.2, stalling request serving for every
    other user of the instance for the duration of each iPhone photo
    (`BE-13`, `PERF-1`).
    """
    import pillow_heif
    from PIL import Image

    pillow_heif.register_heif_opener()
    with Image.open(io.BytesIO(data)) as img:
        buffer = io.BytesIO()
        img.convert("RGB").save(buffer, format="JPEG", quality=90)
        return buffer.getvalue()


async def _normalize(data: bytes, mime: str) -> tuple[bytes, str]:
    """Resolve mime aliases and transcode HEIC to JPEG.

    Raises ValueError when a claimed HEIC photo can't actually be decoded.
    """
    mime = MIME_ALIASES.get(mime, mime)
    if mime in CONVERT_TO_JPEG:
        try:
            data = await asyncio.to_thread(_to_jpeg, data)
        except Exception:  # noqa: BLE001 — a corrupt photo is not a server fault
            # Pillow and pillow-heif raise across a wide surface on a malformed
            # file — UnidentifiedImageError, OSError, struct.error, and whatever
            # the HEIF decoder decides. Narrowing this list would mean a student
            # photographing their homework gets a 500 for the one decoder error
            # nobody enumerated.
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


def safe_filename(name: str) -> str:
    """Strip anything that could break out of a quoted HTTP header value. The
    original filename is client-supplied metadata (`SEC-16`) and reaches a
    Content-Disposition header in two places — a proxied response and a
    signed URL's presigned parameters — so this is shared rather than
    reimplemented at each call site, where the two copies could drift."""
    cleaned = "".join(c for c in name if c.isprintable() and c not in '"\\\r\n')
    return cleaned[:200] or "download"


def content_disposition(filename: str) -> str:
    """A complete `attachment` Content-Disposition value, safe to put in a
    header.

    HTTP headers are latin-1 encoded, so a perfectly ordinary filename — Arabic,
    Chinese, an emoji — raises `UnicodeEncodeError` when the header is built and
    the download 500s. Starlette's `FileResponse` handled this for us before
    task 1.2 replaced it, so this reimplements what it did: an ASCII-only
    `filename=` that any client understands, plus RFC 5987 `filename*=` carrying
    the real name for clients that read it.
    """
    safe = safe_filename(filename)
    ascii_name = safe.encode("ascii", "replace").decode("ascii").replace("?", "_")
    quoted = quote(safe, safe="")
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quoted}"


class ObjectNotFoundError(Exception):
    """Raised by a backend's `download` when the key names no object.

    A distinct type so callers (`api/file_responses.py`) can tell "the row
    points at something that no longer exists" — a 404 — apart from every
    other way a backend can fail — a 502. Without this, a stale row or an
    object expired out of a lifecycle policy surfaced as a bare unhandled 500
    with no distinguishing signal in the response or the log line.
    """


# --------------------------------------------------------------------------- #
# Backends
# --------------------------------------------------------------------------- #


class StorageBackend(Protocol):
    """The storage contract. Implementations must not assume a filesystem.

    `get_signed_url` is deliberately synchronous — presigning is a local
    signature over the request, not a round trip — and returns None on backends
    that cannot mint one, which is how callers decide between redirecting and
    proxying the bytes themselves.
    """

    async def upload(self, key: str, data: bytes, mime: str) -> None: ...

    async def download(self, key: str) -> bytes: ...

    async def delete(self, key: str) -> None: ...

    async def exists(self, key: str) -> bool: ...

    def get_signed_url(
        self, key: str, *, mime: str, filename: str, expires_in: int
    ) -> str | None: ...


class LocalBackend:
    """Files under `UPLOAD_DIR`. The development and test backend.

    Mints no signed URLs: there is no separate origin to redirect to, so callers
    fall back to proxying, which is what they do for sensitive files anyway.
    """

    def _path(self, key: str) -> Path:
        root = Path(get_settings().upload_dir)
        target = (root / key).resolve()
        # Keys are server-generated, so this cannot currently trigger. It is
        # here because that guarantee lives in another function: anything that
        # ever lets a stored key escape the root would otherwise become an
        # arbitrary-file read against the API's own filesystem.
        if not target.is_relative_to(root.resolve()):
            raise ValueError("Resolved key escapes the upload root")
        return target

    async def upload(self, key: str, data: bytes, mime: str) -> None:
        def _write() -> None:
            path = self._path(key)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)

        await asyncio.to_thread(_write)

    async def download(self, key: str) -> bytes:
        def _read() -> bytes:
            try:
                return self._path(key).read_bytes()
            except FileNotFoundError:
                raise ObjectNotFoundError(key) from None

        return await asyncio.to_thread(_read)

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(lambda: self._path(key).unlink(missing_ok=True))

    async def exists(self, key: str) -> bool:
        return await asyncio.to_thread(lambda: self._path(key).is_file())

    def get_signed_url(self, key: str, *, mime: str, filename: str, expires_in: int) -> str | None:
        return None


class S3Backend:
    """Any S3-compatible object store — AWS S3, Cloudflare R2, MinIO.

    boto3 is synchronous, so every call that touches the network is dispatched
    to a thread (`BE-13`). The client is built once per process and is
    thread-safe for these operations.
    """

    def __init__(self) -> None:
        import boto3
        from botocore.config import Config

        settings = get_settings()
        self._bucket = settings.s3_bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url or None,
            region_name=settings.s3_region,
            aws_access_key_id=settings.s3_access_key_id,
            aws_secret_access_key=settings.s3_secret_access_key,
            config=Config(
                # R2 and MinIO reject the newer checksum headers boto3 sends
                # by default; s3v4 is the signature every S3-compatible store
                # accepts.
                signature_version="s3v4",
                # Every call runs inside asyncio.to_thread on the loop's
                # shared default thread pool — the same pool HEIC transcoding
                # and local-disk writes use. Without an explicit ceiling, a
                # hanging endpoint holds a thread for botocore's 60s default,
                # and enough concurrent stuck calls starve unrelated
                # to_thread work too. Fail fast instead.
                connect_timeout=5,
                read_timeout=10,
                retries={"max_attempts": 2},
            ),
        )

    async def upload(self, key: str, data: bytes, mime: str) -> None:
        await asyncio.to_thread(
            self._client.put_object,
            Bucket=self._bucket,
            Key=key,
            Body=data,
            ContentType=mime,
        )

    async def download(self, key: str) -> bytes:
        def _get() -> bytes:
            from botocore.exceptions import ClientError

            try:
                response = self._client.get_object(Bucket=self._bucket, Key=key)
            except ClientError as exc:
                if exc.response.get("Error", {}).get("Code") in ("NoSuchKey", "404"):
                    raise ObjectNotFoundError(key) from None
                raise
            body: bytes = response["Body"].read()
            return body

        return await asyncio.to_thread(_get)

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self._client.delete_object, Bucket=self._bucket, Key=key)

    async def exists(self, key: str) -> bool:
        def _head() -> bool:
            from botocore.exceptions import ClientError

            try:
                self._client.head_object(Bucket=self._bucket, Key=key)
            except ClientError as exc:
                # Only a confirmed "not found" means the object is absent.
                # Anything else — a permissions failure, a misconfigured
                # bucket, throttling — is a real fault and must not be
                # reported as the same thing an absent key would report.
                code = exc.response.get("Error", {}).get("Code")
                if code in ("404", "NoSuchKey", "NotFound"):
                    return False
                raise
            return True

        return await asyncio.to_thread(_head)

    def get_signed_url(self, key: str, *, mime: str, filename: str, expires_in: int) -> str | None:
        # Content-Disposition is signed in rather than trusted from the store,
        # so a file cannot be served inline under a name the uploader chose.
        url: str = self._client.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": self._bucket,
                "Key": key,
                "ResponseContentType": mime,
                "ResponseContentDisposition": content_disposition(filename),
            },
            ExpiresIn=expires_in,
        )
        return url


@lru_cache
def get_storage() -> StorageBackend:
    """The configured backend. Cached per process: constructing the S3 client
    opens no connection, but rebuilding it per request would re-read config and
    re-resolve credentials on every upload."""
    if get_settings().storage_backend == "s3":
        return S3Backend()
    return LocalBackend()


# --------------------------------------------------------------------------- #
# Keys
# --------------------------------------------------------------------------- #


def new_key(organization_id: int, mime: str) -> str:
    """A tenant-scoped, unguessable, server-generated object key (`SEC-16`).

    The organization prefix is what makes a bucket policy or lifecycle rule able
    to talk about one tenant's objects. It is a namespace, not an access
    control: authorization is still enforced per request against the row that
    references the key.
    """
    return f"org/{organization_id}/{secrets.token_hex(16)}{ALLOWED_MIMES[mime]}"


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #


async def save_upload(file: UploadFile, *, organization_id: int) -> tuple[str, str, str]:
    """Persist an uploaded file; returns (object_key, original_name, mime)."""
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
        data, mime = await _normalize(data, mime)
    except ValueError as exc:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, str(exc)) from None
    if not content_matches_mime(data, mime):
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            "This file's contents don't match its type — re-export it as a PDF or image "
            "and try again",
        )
    return await _write(data, mime, file.filename or "upload", organization_id)


async def save_bytes(
    data: bytes, mime: str, filename: str, *, organization_id: int
) -> tuple[str, str, str]:
    """Persist raw bytes fetched from an external source (e.g. a Google Drive
    attachment) under the same validation and layout as a direct upload.
    Raises ValueError (not HTTPException) since callers may be background
    jobs rather than requests."""
    # Cap the *source* bytes before _normalize, which may decode and re-encode
    # a HEIC. Checking only afterwards would both let an arbitrarily large photo
    # through the decoder and measure the (smaller) transcoded JPEG instead.
    if len(data) > MAX_FILE_BYTES:
        raise ValueError("File exceeds the 20 MB limit")
    data, mime = await _normalize(data, mime)
    if mime not in ALLOWED_MIMES:
        raise ValueError(f"Unsupported file type: {mime}")
    if len(data) > MAX_FILE_BYTES:
        raise ValueError("File exceeds the 20 MB limit")
    if not content_matches_mime(data, mime):
        raise ValueError(f"File contents do not match the declared type: {mime}")
    return await _write(data, mime, filename, organization_id)


async def _write(
    data: bytes, mime: str, filename: str, organization_id: int
) -> tuple[str, str, str]:
    key = new_key(organization_id, mime)
    await get_storage().upload(key, data, mime)
    return key, filename, mime


async def delete_file(key: str) -> None:
    """Remove a stored object, tolerating one that is already gone.

    Used to undo writes when a later step in the same request fails — an object
    with no row pointing at it is invisible and can never be cleaned up.
    """
    await get_storage().delete(key)


async def read_file(key: str) -> bytes:
    return await get_storage().download(key)


def signed_url(key: str, *, mime: str, filename: str) -> str | None:
    """A short-lived download URL, or None if the backend cannot mint one.

    Minted per request and only after the caller's authorization check has
    passed (threat review F3). Never cache the result, never reuse it across
    requests, and never log it — a signed URL is a bearer credential.
    """
    return get_storage().get_signed_url(
        key,
        mime=mime,
        filename=filename,
        expires_in=get_settings().signed_url_ttl_seconds,
    )
