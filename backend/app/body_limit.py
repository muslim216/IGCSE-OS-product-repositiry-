"""A ceiling on how much a single request may send (`SA-08`, `SR-F`).

Nothing bounded a request body. A file upload is parsed to temporary files
before any handler runs, so its 20 MB per-file check came after the whole body
had already been taken in, and an ordinary JSON request with a megabyte-sized
"reason" was parsed and stored. One account could fill the disk or memory of
the single instance everyone shares.

Two ceilings: file uploads get the larger one, everything else 1 MB, which no
form in the product comes near. Checked against `Content-Length` up front and
against the bytes actually received, since a chunked body has no length.
"""

from fastapi import HTTPException, status
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

#: Every request that is not a file upload: JSON bodies, sign-in, settings.
MAX_PLAIN_BODY_BYTES = 1024 * 1024

_TOO_LARGE = "This request is too large. Send fewer or smaller files at a time."


class BodySizeLimit:
    def __init__(self, app: ASGIApp, *, max_upload_bytes: int) -> None:
        self.app = app
        self.max_upload_bytes = max_upload_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(scope["headers"])
        is_upload = headers.get(b"content-type", b"").startswith(b"multipart/form-data")
        limit = self.max_upload_bytes if is_upload else MAX_PLAIN_BODY_BYTES

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
