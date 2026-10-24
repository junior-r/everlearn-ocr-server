"""Reading text from an image: decoding plus the RapidOCR call."""

from __future__ import annotations

import io
from typing import Protocol

from PIL import Image, ImageOps, UnidentifiedImageError
from rapidocr import RapidOCR

from .layout import TextBox

# Refuse absurdly large images instead of decompressing them into memory
Image.MAX_IMAGE_PIXELS = 40_000_000


class UnreadableImageError(ValueError):
    """The bytes are not an image Pillow can decode."""


class OcrEngine(Protocol):
    def read(self, image_bytes: bytes) -> list[TextBox]: ...


def decode_image(image_bytes: bytes) -> Image.Image:
    """Decodes a photo and turns it upright."""
    try:
        image = Image.open(io.BytesIO(image_bytes))
        image.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as error:
        raise UnreadableImageError(str(error)) from error
    # Phone cameras store rotation as metadata rather than rotating the pixels
    return ImageOps.exif_transpose(image).convert("RGB")


class RapidOcrEngine:
    """PaddleOCR's detection and recognition models, run on the CPU with ONNX Runtime."""

    def __init__(self) -> None:
        self._ocr = RapidOCR(params={"Global.log_level": "error"})

    def read(self, image_bytes: bytes) -> list[TextBox]:
        result = self._ocr(decode_image(image_bytes))
        if result.boxes is None or result.txts is None or result.scores is None:
            return []
        return [
            TextBox(
                text=text,
                left=float(min(x for x, _ in polygon)),
                top=float(min(y for _, y in polygon)),
                right=float(max(x for x, _ in polygon)),
                bottom=float(max(y for _, y in polygon)),
                score=float(score),
            )
            for polygon, text, score in zip(result.boxes, result.txts, result.scores, strict=True)
        ]
