"""What one request may send (`SA-08`, `SR-F`, `SA-07`).

Nothing bounded a request: an upload was parsed whole before its 20 MB check,
a JSON body of any size was parsed and stored, and one hand-in could carry any
number of files. The ceilings are lowered in these tests so they prove the
check without sending what it protects against.
"""

import pytest
from fastapi import FastAPI, File, UploadFile
from httpx import ASGITransport, AsyncClient

from app import body_limit
from app.config import get_settings
from app.services import storage
from tests.conftest import PNG_BYTES

API = "/api/v1"


@pytest.fixture
def small_plain_ceiling(monkeypatch):
    monkeypatch.setattr(body_limit, "MAX_PLAIN_BODY_BYTES", 1000)


# --- The plain ceiling -----------------------------------------------------


@pytest.mark.usefixtures("small_plain_ceiling")
async def test_a_json_body_over_the_plain_ceiling_is_a_413(client):
    resp = await client.post(f"{API}/auth/login", json={"identifier": "a" * 2000, "password": "x"})
    assert resp.status_code == 413, resp.text
    assert "too large" in resp.json()["detail"]
    # Still carries what every response carries (it runs inside them).
    assert resp.headers.get("X-Request-ID")


async def test_a_json_body_under_the_ceiling_is_handled_as_before(client):
    resp = await client.post(f"{API}/auth/login", json={"identifier": "a", "password": "x"})
    assert resp.status_code == 401, resp.text


@pytest.mark.usefixtures("small_plain_ceiling")
async def test_a_body_without_a_length_is_counted_as_it_arrives(client):
    """A chunked body declares no length, so the bytes are counted as read."""

    async def chunks():
        for _ in range(5):
            yield b"x" * 400

    resp = await client.post(
        f"{API}/auth/login", content=chunks(), headers={"Content-Type": "application/json"}
    )
    assert resp.status_code == 413, resp.text


@pytest.mark.usefixtures("small_plain_ceiling")
async def test_calling_a_json_route_multipart_does_not_buy_the_upload_ceiling(client):
    """The client names its own content type; the sign-in route reads its whole
    body before anything else runs."""
    resp = await client.post(
        f"{API}/auth/login",
        files=[("identifier", ("a.txt", b"x" * 5000, "text/plain"))],
    )
    assert resp.status_code == 413, resp.text


@pytest.mark.usefixtures("small_plain_ceiling")
async def test_a_signed_in_caller_gets_no_upload_ceiling_on_a_route_without_files(client, student):
    """Signed in is not enough: the route must take files."""
    resp = await client.post(
        f"{API}/auth/login",
        files=[("identifier", ("a.txt", b"x" * 5000, "text/plain"))],
        headers=student["headers"],
    )
    assert resp.status_code == 413, resp.text


@pytest.mark.usefixtures("small_plain_ceiling")
async def test_an_upload_without_a_sign_in_is_held_to_the_plain_ceiling(
    client, published_assignment
):
    """Files are parsed to disk before the route checks who is asking."""
    resp = await client.post(
        f"{API}/assignments/{published_assignment['id']}/submissions",
        files=[("files", ("p.png", PNG_BYTES + b"x" * 5000, "image/png"))],
    )
    assert resp.status_code == 413, resp.text


@pytest.mark.usefixtures("small_plain_ceiling")
async def test_a_signed_in_upload_gets_the_upload_ceiling(client, student, published_assignment):
    resp = await client.post(
        f"{API}/assignments/{published_assignment['id']}/submissions",
        files=[("files", ("p.png", PNG_BYTES + b"x" * 5000, "image/png"))],
        headers=student["headers"],
    )
    assert resp.status_code == 201, resp.text


def test_every_route_that_takes_files_gets_the_upload_ceiling():
    """Found from the app's own OpenAPI, so a new upload route needs no list."""
    from app.main import app

    found = {(m, p.pattern) for m, p in body_limit.upload_routes(app.openapi())}
    assert ("POST", "^/api/v1/assignments/(?P<assignment_id>[^/]+)/submissions$") in found
    assert ("POST", "^/api/v1/syllabus\\-uploads$") in found
    assert not any("auth" in pattern for _, pattern in found)


# --- The upload ceiling, on a small app of its own ---------------------------


def _small_app(max_upload_bytes: int) -> FastAPI:
    app = FastAPI()

    @app.post("/upload")
    async def upload(files: list[UploadFile] = File()) -> dict:  # noqa: B008
        return {"files": len(files)}

    app.add_middleware(
        body_limit.BodySizeLimit, max_upload_bytes=max_upload_bytes, openapi=app.openapi
    )
    return app


async def test_a_signed_in_upload_over_the_upload_ceiling_is_a_413(student):
    transport = ASGITransport(app=_small_app(3000))
    async with AsyncClient(transport=transport, base_url="http://test") as small:
        over = await small.post(
            "/upload",
            files=[("files", ("p.png", b"x" * 5000, "image/png"))],
            headers=student["headers"],
        )
        under = await small.post(
            "/upload",
            files=[("files", ("p.png", b"x" * 2000, "image/png"))],
            headers=student["headers"],
        )
    assert over.status_code == 413, over.text
    assert under.status_code == 200, under.text


async def test_a_declared_length_over_the_ceiling_is_refused_before_reading_any_body():
    """`Content-Length` alone is enough: nothing is read or parsed."""
    reached, reads, sent = [], [], []

    async def app(scope, receive, send):
        reached.append(1)

    async def receive():
        reads.append(1)
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    limit = body_limit.BodySizeLimit(app, max_upload_bytes=10, openapi=lambda: {})
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/x",
        "headers": [(b"content-type", b"application/json"), (b"content-length", b"2000000")],
    }
    await limit(scope, receive, send)
    assert reached == [] and reads == []
    assert sent[0]["status"] == 413


# --- Files per hand-in -----------------------------------------------------


@pytest.mark.parametrize("route", ["homework", "past paper", "mock"])
async def test_more_files_than_the_ceiling_is_refused(
    client, student, published_assignment, monkeypatch, route
):
    monkeypatch.setattr(get_settings(), "max_files_per_upload", 2)
    files = [("files", (f"p{i}.png", PNG_BYTES, "image/png")) for i in range(3)]
    # The past-paper and mock routes refuse before even looking the paper up.
    path = {
        "homework": f"{API}/assignments/{published_assignment['id']}/submissions",
        "past paper": f"{API}/past-papers/999999/attempts",
        "mock": f"{API}/mocks/999999/submissions",
    }[route]
    resp = await client.post(
        path, files=files, data={"attempted_at": "2026-10-01"}, headers=student["headers"]
    )
    assert resp.status_code == 413, resp.text
    assert "Up to 2 files" in resp.json()["detail"]


async def test_files_up_to_the_ceiling_are_accepted(
    client, student, published_assignment, monkeypatch
):
    monkeypatch.setattr(get_settings(), "max_files_per_upload", 2)
    files = [("files", (f"p{i}.png", PNG_BYTES, "image/png")) for i in range(2)]
    resp = await client.post(
        f"{API}/assignments/{published_assignment['id']}/submissions",
        files=files,
        headers=student["headers"],
    )
    assert resp.status_code == 201, resp.text


# --- One file --------------------------------------------------------------


async def test_an_oversized_file_is_refused_having_read_only_past_the_cap(monkeypatch):
    """Read to one byte past the cap, never the whole file (`SEC-17`)."""
    monkeypatch.setattr(storage, "MAX_FILE_BYTES", 100)
    asked: list[int] = []

    class Upload:
        content_type = "image/png"
        filename = "big.png"

        async def read(self, size: int = -1) -> bytes:
            asked.append(size)
            data = PNG_BYTES + b"x" * 10_000
            return data if size < 0 else data[:size]

    with pytest.raises(Exception) as raised:
        await storage.save_upload(Upload(), organization_id=1)
    assert getattr(raised.value, "status_code", None) == 413
    assert asked == [101]
