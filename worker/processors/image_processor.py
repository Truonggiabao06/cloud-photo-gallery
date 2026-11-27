"""Validate uploaded images and generate bounded WebP thumbnails."""
from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import warnings

from PIL import Image, ImageOps, UnidentifiedImageError


class InvalidImageError(Exception):
    """The source bytes are not a supported, safe image."""


@dataclass(frozen=True)
class Thumbnail:
    name: str
    width: int
    height: int
    data: bytes
    content_type: str = "image/webp"


_FORMAT_TO_MIME = {
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "WEBP": "image/webp",
}


def create_thumbnails(
    image_bytes: bytes,
    *,
    expected_mime_type: str | None = None,
    max_pixels: int = 40_000_000,
) -> tuple[Thumbnail, Thumbnail]:
    """Create 200x200 and 800x800 max-bound WebP images without upscaling.

    The first frame is used for animated WEBP files. EXIF orientation is applied
    and source metadata is not copied into the derived files.
    """
    if not image_bytes:
        raise InvalidImageError("Original image is empty")
    if max_pixels < 1:
        raise ValueError("max_pixels must be positive")

    try:
        # Turn Pillow's decompression-bomb warning into a hard rejection.
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(image_bytes)) as probe:
                actual_mime = _FORMAT_TO_MIME.get(probe.format or "")
                if actual_mime is None:
                    raise InvalidImageError(f"Unsupported image format: {probe.format}")
                if expected_mime_type and actual_mime != expected_mime_type:
                    raise InvalidImageError(
                        f"Image content is {actual_mime}, but Backend declared {expected_mime_type}"
                    )
                if probe.width * probe.height > max_pixels:
                    raise InvalidImageError(
                        f"Image dimensions exceed the {max_pixels:,}-pixel processing limit"
                    )
                probe.verify()

            with Image.open(BytesIO(image_bytes)) as source:
                if source.width * source.height > max_pixels:
                    raise InvalidImageError(
                        f"Image dimensions exceed the {max_pixels:,}-pixel processing limit"
                    )
                # Animated inputs are intentionally reduced to their first frame.
                try:
                    source.seek(0)
                except EOFError:
                    pass
                image = ImageOps.exif_transpose(source)
                image.load()

                has_alpha = image.mode in {"RGBA", "LA"} or (
                    image.mode == "P" and "transparency" in image.info
                )
                normalized = image.convert("RGBA" if has_alpha else "RGB")

                outputs: list[Thumbnail] = []
                for name, bounds in (("small", (200, 200)), ("large", (800, 800))):
                    thumb = normalized.copy()
                    thumb.thumbnail(bounds, Image.Resampling.LANCZOS)
                    output = BytesIO()
                    thumb.save(output, format="WEBP", quality=85, method=6)
                    outputs.append(
                        Thumbnail(
                            name=name,
                            width=thumb.width,
                            height=thumb.height,
                            data=output.getvalue(),
                        )
                    )
                normalized.close()
                return outputs[0], outputs[1]
    except InvalidImageError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise InvalidImageError(f"Cannot safely decode image: {exc}") from exc
