"""How a stored file reaches the caller.

Serving splits by sensitivity (threat review F3), and the split is deliberate:

* `proxied_file` streams the bytes through the API, so the caller's ownership
  check has already run on *this* request. Revocation is instant. Student
  submissions are served this way because they are photographs of a named
  minor's marked work.
* `signed_or_proxied_file` hands back a short-lived URL to the object store
  instead, keeping the megabytes off the API. A signed URL is a bearer
  credential: it can be forwarded, screenshotted, or captured from a log, and
  it cannot be revoked before it expires. Only files carrying no personal data
  are served this way — mark schemes, classifieds, past papers, teaching
  material.

Never log the URL these mint, and never cache one across requests: it is minted
per request and only after authorization has passed.
"""

import logging

from fastapi import HTTPException, Response, status
from fastapi.responses import RedirectResponse

from app.services import storage

log = logging.getLogger("api")


#: Files are always attachments, never rendered inline. A PDF opened inline
#: executes in the origin's context; served as an attachment it does not.
_disposition = storage.content_disposition

#: Both serving paths carry this. The proxied path needs it *more* than the
#: signed one, not less: a bearer URL at least expires on its own, while these
#: are the submission bytes themselves — a named minor's marked work — and an
#: `Authorization` request header does not reliably stop a browser or shared
#: cache from retaining the response.
_NO_STORE = "no-store, private"


async def proxied_file(key: str, *, mime: str, filename: str) -> Response:
    """Return the bytes through the API. Use when the authorization check must
    run on every single view.

    A missing object (a stale row, an object removed independently of its
    row) becomes a 404 rather than an unhandled 500; any other storage
    failure — a network blip, a misconfigured bucket — becomes a 502 with the
    key logged, since the caller can retry but cannot fix it.
    """
    try:
        data = await storage.read_file(key)
    except storage.ObjectNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found") from None
    except Exception:
        log.exception("could not read stored object key=%s", key)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, "Storage is temporarily unavailable"
        ) from None
    return Response(
        content=data,
        media_type=mime,
        headers={
            "Content-Disposition": _disposition(filename),
            "Cache-Control": _NO_STORE,
        },
    )


async def signed_or_proxied_file(key: str, *, mime: str, filename: str) -> Response:
    """Redirect to a short-lived signed URL, falling back to proxying when the
    backend cannot mint one.

    The fallback is what keeps local development and the test suite working
    without an object store, and it is safe by construction: proxying is the
    stricter of the two paths, never the weaker one.
    """
    try:
        url = storage.signed_url(key, mime=mime, filename=filename)
    except Exception:
        # Signing is a local computation, but it can still fail on a
        # misconfigured client. Falling back to proxying degrades to the
        # stricter path and keeps the download working, which is what the
        # backend-cannot-sign branch below already does.
        log.exception("could not mint a signed URL; proxying instead key=%s", key)
        url = None
    if url is None:
        return await proxied_file(key, mime=mime, filename=filename)
    # 307 rather than 302: the method must be preserved, and a cached 302 for a
    # URL that expires in minutes would serve an expired credential. no-store
    # makes that invariant part of the response itself rather than only a
    # comment — a 307 is unlikely to be cached by a conformant client even
    # without it, but the URL is a bearer credential and this is cheap.
    return RedirectResponse(url, status_code=307, headers={"Cache-Control": _NO_STORE})
