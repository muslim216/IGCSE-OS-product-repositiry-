"""Storage backend contract and the F3 serving split (task 1.2, AV-82).

The object-key assertions here are required by the plan explicitly: keys must
be tenant-scoped and unguessable "in a test, not by convention".
"""

import asyncio
import re

import pytest

from app.services import storage

PDF_BYTES = b"%PDF-1.4 fake pdf for tests"


# --------------------------------------------------------------------------- #
# Object keys (SEC-16)
# --------------------------------------------------------------------------- #


def test_keys_are_tenant_scoped():
    """An object key names the organization that owns it, so a bucket policy or
    lifecycle rule can talk about one tenant's objects."""
    key = storage.new_key(42, "application/pdf")
    assert key.startswith("org/42/")


def test_keys_from_different_tenants_share_no_prefix():
    a = storage.new_key(1, "application/pdf")
    b = storage.new_key(2, "application/pdf")
    assert a.split("/")[:2] != b.split("/")[:2]


def test_keys_are_unguessable():
    """128 bits of randomness in the filename. Enumerable keys would make the
    object store readable to anyone who could reach it, independently of the
    authorization the API applies."""
    key = storage.new_key(1, "application/pdf")
    name = key.rsplit("/", 1)[-1].removesuffix(".pdf")
    assert re.fullmatch(r"[0-9a-f]{32}", name)

    keys = {storage.new_key(1, "application/pdf") for _ in range(500)}
    assert len(keys) == 500


async def test_key_contains_no_user_controlled_fragment():
    """The client's filename is metadata only (SEC-16). It must never reach the
    key, or a crafted name becomes a path in the object store."""
    key, name, _mime = await storage.save_bytes(
        PDF_BYTES,
        "application/pdf",
        "../../etc/passwd; DROP TABLE users.pdf",
        organization_id=7,
    )
    assert key.startswith("org/7/")
    assert ".." not in key
    assert "passwd" not in key
    # ...but it is still preserved as metadata for display.
    assert name == "../../etc/passwd; DROP TABLE users.pdf"


# --------------------------------------------------------------------------- #
# Backend contract
# --------------------------------------------------------------------------- #


async def test_round_trip_through_the_backend():
    key, _name, _mime = await storage.save_bytes(
        PDF_BYTES, "application/pdf", "paper.pdf", organization_id=1
    )
    backend = storage.get_storage()
    assert await backend.exists(key)
    assert await storage.read_file(key) == PDF_BYTES
    await storage.delete_file(key)
    assert not await backend.exists(key)


async def test_deleting_a_missing_object_is_tolerated():
    """Undoing a partial write must not fail on a file that never landed."""
    await storage.delete_file("org/1/does-not-exist.pdf")


async def test_local_backend_refuses_a_key_that_escapes_the_root():
    """Keys are server-generated, so this cannot happen today. The guard exists
    because that guarantee lives in a different function."""
    backend = storage.LocalBackend()
    with pytest.raises(ValueError, match="escapes the upload root"):
        await backend.download("../../../../etc/passwd")


def test_local_backend_mints_no_signed_url():
    """There is no second origin to redirect to, so callers must proxy."""
    assert (
        storage.LocalBackend().get_signed_url(
            "org/1/x.pdf", mime="application/pdf", filename="x.pdf", expires_in=300
        )
        is None
    )


# --------------------------------------------------------------------------- #
# Event loop (BE-13, PERF-1)
# --------------------------------------------------------------------------- #


async def test_heic_transcode_does_not_block_the_event_loop():
    """Decode-and-re-encode is CPU-bound. Until task 1.2 it ran inline, stalling
    request serving for every other user of the instance for the duration of
    each iPhone photo."""
    import io

    import pillow_heif
    from PIL import Image

    pillow_heif.register_heif_opener()
    buffer = io.BytesIO()
    Image.new("RGB", (400, 400), (10, 90, 140)).save(buffer, format="HEIF")

    ticks = 0

    async def heartbeat() -> None:
        nonlocal ticks
        while True:
            await asyncio.sleep(0)
            ticks += 1

    beat = asyncio.create_task(heartbeat())
    try:
        _data, mime = await storage._normalize(buffer.getvalue(), "image/heic")
    finally:
        beat.cancel()

    assert mime == "image/jpeg"
    # A blocking transcode yields nothing at all; the awaited version hands
    # control back while the worker thread runs.
    assert ticks > 0, "the event loop was blocked for the whole transcode"


# --------------------------------------------------------------------------- #
# Signed URLs (threat review F3)
#
# The fake signing backend and the `signing_storage` fixture live in
# conftest.py (as `FakeSigningBackend`) rather than here, since
# test_homework.py's F3 serving-split tests need it too.
# --------------------------------------------------------------------------- #


def test_signed_urls_carry_the_configured_expiry(signing_storage):
    from app.config import get_settings

    url = storage.signed_url("org/1/x.pdf", mime="application/pdf", filename="x.pdf")
    assert url is not None
    assert f"expires={get_settings().signed_url_ttl_seconds}" in url


def test_signed_urls_are_not_reused_across_calls(signing_storage, monkeypatch):
    """Minted per request, after authorization — never cached (F3)."""
    calls = []
    original = signing_storage.get_signed_url

    def counting(key, **kwargs):
        calls.append(key)
        return original(key, **kwargs)

    monkeypatch.setattr(signing_storage, "get_signed_url", counting)
    storage.signed_url("org/1/x.pdf", mime="application/pdf", filename="x.pdf")
    storage.signed_url("org/1/x.pdf", mime="application/pdf", filename="x.pdf")
    assert len(calls) == 2


# --------------------------------------------------------------------------- #
# Content-Disposition header safety
# --------------------------------------------------------------------------- #


def test_a_non_ascii_filename_produces_a_header_that_can_be_encoded():
    """HTTP headers are latin-1. A perfectly ordinary Arabic or Chinese
    filename raised UnicodeEncodeError when the header was built, 500ing a
    valid download — Starlette's FileResponse handled this before task 1.2
    replaced it."""
    value = storage.content_disposition("واجب الطالب.pdf")
    value.encode("latin-1")  # must not raise
    assert "filename*=UTF-8''" in value


def test_content_disposition_still_blocks_header_injection():
    """The property that matters is that a crafted name cannot *break out* of
    the header — no CR/LF to start a new one, no bare quote to end the value
    early. Surviving as literal text inside the quoted filename is harmless."""
    value = storage.content_disposition('evil".pdf\r\nX-Injected: 1')
    value.encode("latin-1")
    assert "\r" not in value and "\n" not in value
    # Exactly two quotes: the ones opening and closing the filename value.
    assert value.count('"') == 2


def test_content_disposition_always_marks_the_file_as_an_attachment():
    """Never inline: a PDF opened inline executes in the origin's context."""
    assert storage.content_disposition("x.pdf").startswith("attachment;")
