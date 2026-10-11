"""Reading text from an image: preprocessing plus the Tesseract call."""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Protocol

import pytesseract
from PIL import Image, ImageOps, UnidentifiedImageError

# Refuse absurdly large images instead of decompressing them into memory
Image.MAX_IMAGE_PIXELS = 40_000_000

_TARGET_WIDTH = 1800
_MAX_UPSCALE = 3.0
_MIN_SIDE = 64


class UnreadableImageError(ValueError):
    """The bytes are not an image Pillow can decode."""


@dataclass(frozen=True)
class OcrText:
    text: str
    # Mean confidence Tesseract reported for the words it read, from 0 to 1
    confidence: float


class OcrEngine(Protocol):
    def read(self, image_bytes: bytes, page_segmentation_mode: int) -> OcrText: ...


def prepare_image(image_bytes: bytes) -> Image.Image:
    """Decodes and normalises a photo for OCR: upright, greyscale, large enough, high contrast."""
    try:
        image = Image.open(io.BytesIO(image_bytes))
        image.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as error:
        raise UnreadableImageError(str(error)) from error
    # Phone cameras store rotation as metadata rather than rotating the pixels
    image = ImageOps.exif_transpose(image).convert("L")
    # Tesseract is most accurate when capital letters are roughly 30 px tall
    scale = min(_MAX_UPSCALE, _TARGET_WIDTH / image.width)
    if scale > 1.05:
        size = (round(image.width * scale), round(image.height * scale))
        image = image.resize(size, Image.Resampling.LANCZOS)
    return ImageOps.autocontrast(image, cutoff=1)


class TesseractEngine:
    def __init__(self, languages: str) -> None:
        self._languages = languages

    def read(self, image_bytes: bytes, page_segmentation_mode: int) -> OcrText:
        image = prepare_image(image_bytes)
        # Too small to hold legible text, and Tesseract errors out on such images
        if min(image.size) < _MIN_SIDE:
            return OcrText(text="", confidence=0.0)
        try:
            data = pytesseract.image_to_data(
                image,
                lang=self._languages,
                config=f"--psm {page_segmentation_mode}",
                output_type=pytesseract.Output.DICT,
            )
        except pytesseract.TesseractError:
            # A valid image Tesseract cannot process is "nothing readable", not a server fault
            return OcrText(text="", confidence=0.0)
        lines: dict[tuple[int, int, int], list[str]] = {}
        confidences: list[float] = []
        for index, word in enumerate(data["text"]):
            confidence = float(data["conf"][index])
            if not word.strip() or confidence < 0:
                continue
            key = (data["block_num"][index], data["par_num"][index], data["line_num"][index])
            lines.setdefault(key, []).append(word)
            confidences.append(confidence)
        text = "\n".join(" ".join(words) for words in lines.values())
        mean = sum(confidences) / len(confidences) / 100 if confidences else 0.0
        return OcrText(text=text, confidence=mean)
