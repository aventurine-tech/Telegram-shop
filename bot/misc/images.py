"""Validation of uploaded product pictures. The bytes are stored exactly as uploaded."""
import io

from PIL import Image, UnidentifiedImageError

MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_IMAGE_PIXELS = 50_000_000
ALLOWED_FORMATS = frozenset({"JPEG", "PNG", "WEBP"})


class ImageError(Exception):
    """Raised with a stable code: ``too_large``, ``invalid_image`` or ``unsupported_format``."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def validate_image(data: bytes) -> str:
    """Check that ``data`` is a real, reasonably sized JPEG/PNG/WEBP and return its format name.

    ``verify()`` catches truncated and garbage files without decoding every pixel; the size is
    checked from the header first so a decompression bomb is never expanded.
    """
    if not data:
        raise ImageError("invalid_image")
    if len(data) > MAX_IMAGE_BYTES:
        raise ImageError("too_large")
    try:
        with Image.open(io.BytesIO(data)) as img:
            fmt = img.format
            width, height = img.size
            if width * height > MAX_IMAGE_PIXELS:
                raise ImageError("too_large")
            img.verify()
    except ImageError:
        raise
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError, Image.DecompressionBombError):
        raise ImageError("invalid_image")
    if fmt not in ALLOWED_FORMATS:
        raise ImageError("unsupported_format")
    return fmt
