"""A ceiling on how much a single request may send (`SA-08`, `SR-F`).

Nothing bounded a request body. A file upload is parsed to temporary files
before any handler runs — before even the sign-in check — so its 20 MB per-file
check came after the whole body had already been taken in, and an ordinary JSON
request with a megabyte-sized "reason" was parsed and stored. One caller could
fill the disk or memory of the single instance everyone shares.

Two ceilings. The larger one is for a signed-in caller sending files to a route
that takes files; everything else gets 1 MB, which no form in the product comes
near. Both conditions, not the content type alone: the client names its own
content type, and a JSON route reads its whole body before anything else runs,
so "multipart" on the sign-in route would otherwise have bought 150 MB. Checked
against `Content-Length` up front and against the bytes actually received,
since a chunked body has no length.
"""

import re
from collections.abc import Callable
from typing import Any

from fastapi import HTTPException, status
from starlette.responses import JSONResponse
from starlette.routing import compile_path
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.security import decode_token

#: Every request that is not a signed-in file upload.
MAX_PLAIN_BODY_BYTES = 1024 * 1024

_TOO_LARGE = "This request is too large. If you are adding files, send fewer or smaller ones."


def upload_routes(openapi: dict[str, Any]) -> list[tuple[str, re.Pattern[str]]]:
    """(method, path pattern) for every operation whose request body is
    multipart. Read from the app's own OpenAPI document, so it follows the
    routes themselves: a new upload route needs no entry here."""
    found = []
    for path, operations in openapi.get("paths", {}).items():
        for method, operation in operations.items():
            content = operation.get("requestBody", {}).get("content", {})
            if "multipart/form-data" in content:
                found.append((method.upper(), compile_path(path)[0]))
    return found


def _signed_in(headers: dict[bytes, bytes]) -> bool:
    scheme, _, token = headers.get(b"authorization", b"").decode("latin-1").partition(" ")
    return scheme.lower() == "bearer" and decode_token(token, "access") is not None


class BodySizeLimit:
    def __init__(
        self,
        app: ASGIApp,
        *,
        max_upload_bytes: int,
        openapi: Callable[[], dict[str, Any]],
    ) -> None:
        self.app = app
        self.max_upload_bytes = max_upload_bytes
        # Read on first use: the routers are mounted after this is added.
        self._openapi = openapi
        self._uploads: list[tuple[str, re.Pattern[str]]] | None = None

    def _is_upload_route(self, scope: Scope) -> bool:
        if self._uploads is None:
            self._uploads = upload_routes(self._openapi())
        method, path = scope["method"], scope["path"]
        return any(m == method and pattern.match(path) for m, pattern in self._uploads)

    def _limit(self, scope: Scope, headers: dict[bytes, bytes]) -> int:
        content_type = headers.get(b"content-type", b"").lower()
        if (
            content_type.startswith(b"multipart/form-data")
            and self._is_upload_route(scope)
            and _signed_in(headers)
        ):
            return self.max_upload_bytes
        return MAX_PLAIN_BODY_BYTES

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(scope["headers"])
        limit = self._limit(scope, headers)

        declared = headers.get(b"content-length", b"")
        if declared.isdigit() and int(declared) > limit:
            response = JSONResponse({"detail": _TOO_LARGE}, status_code=413)
            await response(scope, receive, send)
            return

        received = 0

        async def counted() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    # An HTTPException, because FastAPI turns anything else
                    # raised while it reads the body into a 400 and lets this
                    # one through to its handler as a 413.
                    raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, _TOO_LARGE)
            return message

        await self.app(scope, counted, send)
