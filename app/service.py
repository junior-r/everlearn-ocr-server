"""The extraction use case: read the image, parse the text, score the result."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .engine import OcrEngine
from .parser import ExtractedFields, parse_document

# Tesseract page segmentation modes: 6 reads one uniform block of text, which
# suits a tightly cropped card; 11 finds sparse text anywhere, which rescues
# photos with a lot of background or a busy design.
_BLOCK_OF_TEXT = 6
_SPARSE_TEXT = 11
_TOTAL_FIELDS = 4


@dataclass(frozen=True)
class Extraction:
    fields: ExtractedFields
    # How much to trust the result: OCR certainty scaled by how many fields were found
    confidence: float


def extract_identity(engine: OcrEngine, image_bytes: bytes, today: date | None = None) -> Extraction:
    """Reads an ID photo. Runs a second pass in another layout mode only when the first finds little."""
    best: Extraction | None = None
    for mode in (_BLOCK_OF_TEXT, _SPARSE_TEXT):
        read = engine.read(image_bytes, mode)
        fields = parse_document(read.text, today)
        candidate = Extraction(fields, round(read.confidence * fields.found / _TOTAL_FIELDS, 3))
        if best is None or candidate.fields.found > best.fields.found:
            best = candidate
        if best.fields.found >= _TOTAL_FIELDS - 1:
            break
    assert best is not None
    return best
