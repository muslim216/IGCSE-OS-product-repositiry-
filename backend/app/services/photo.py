"""Turning an iPhone photo (HEIC) into a JPEG.

Runs only inside the photo child (`services/pdf_child.py --kind photo`), the
one module that imports Pillow or the HEIF decoder. Both are native code and
any student reaches them with one upload, so they never load in the API
process; `tests/test_pdf_guards.py` holds this file to that.

iPhones photograph in HEIC by default, which is most of what students upload,
and the marking pipeline passes the stored type straight to an image API that
does not take HEIC, so photos are converted on the way in.
"""

import io

import pillow_heif
from PIL import Image
from pillow_heif import options

#: The only decoders libheif may have. A HEIF file names its own codec, and
#: the container also carries AV1 (AVIF) and other codings; with only an HEVC
#: decoder plugin listed, libheif has no plugin for a photo coded any other
#: way, and refuses it. pillow-heif does not say which codec a picture uses
#: before decoding it, so this is checked on the decoders instead, when the
#: child starts: a wheel that ever adds another stops photo reading loudly
#: (a set-up failure, retried and logged) rather than widening it silently.
ALLOWED_DECODERS = frozenset({"libde265"})


class OverCeiling(ValueError):
    """More pixels than the ceiling, read from the header before decoding."""


class NotHeif(ValueError):
    """Pillow opened it as something other than a HEIF picture."""


def configure() -> None:
    """Set the decoder up lean, and refuse to run if its own safety limits are
    off or it could decode anything but HEVC. Called once by the child before
    it says it is ready, so a decoder that cannot be set up this way is a
    broken image, retried, not a bad photo.

    One decoder thread: each thread is a stack and an allocator arena of
    address space, which the child's memory limit counts. No thumbnails,
    depth maps or auxiliary images: the JPEG is made from the main picture
    alone, and each of those is more for a crafted file to make the decoder
    read."""
    options.DECODE_THREADS = 1
    options.THUMBNAILS = False
    options.DEPTH_IMAGES = False
    options.AUX_IMAGES = False
    if options.DISABLE_SECURITY_LIMITS:
        raise RuntimeError("the HEIF decoder's own limits are switched off")
    decoders = set(pillow_heif.libheif_info().get("decoders", {}))
    if not decoders or decoders - ALLOWED_DECODERS:
        raise RuntimeError("the HEIF decoder set is not the expected one")
    pillow_heif.register_heif_opener()


def to_jpeg(data: bytes, *, max_pixels: int) -> bytes:
    """The photo as a JPEG at quality 90. `configure` must have run. Raises
    `OverCeiling` above `max_pixels`, and whatever the libraries raise for
    anything they cannot read, which the child reports as unreadable.

    The JPEG carries none of the photo's metadata: no EXIF, so no location.
    Pillow writes metadata only when asked to, and this never asks."""
    # `open` reads only the header; nothing is decoded until `save`. HEIF
    # only: Pillow opens any format it knows, and the type the upload was sent
    # with is the client's word (`SEC-15`). AVIF is left out on purpose, so
    # Pillow's own AVIF decoder is never reachable from here. (On first use
    # Pillow's `init()` imports its plugin modules, which registers them and
    # decodes nothing; `formats` then confines `open` to this one.)
    with Image.open(io.BytesIO(data), formats=["HEIF"]) as img:
        if img.format != "HEIF":
            raise NotHeif("not a HEIF image")
        # Before `save`, which is where the pixels are decoded: the ceiling is
        # read from the header and nothing larger is ever decoded.
        if img.width * img.height > max_pixels:
            raise OverCeiling("over the pixel ceiling")
        # An RGB picture is saved as it is: `convert` to the same mode copies
        # every pixel, a second full-size picture at the peak.
        picture = img if img.mode == "RGB" else img.convert("RGB")
        buffer = io.BytesIO()
        picture.save(buffer, format="JPEG", quality=90)
        return buffer.getvalue()
