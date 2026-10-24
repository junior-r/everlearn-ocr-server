"""The extraction use case: read the image once, parse the boxes, score the result."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .engine import OcrEngine
from .parser import ExtractedFields, parse_document

_TOTAL_FIELDS = 4


@dataclass(frozen=True)
class Extraction:
    fields: ExtractedFields
    # How much to trust the result: OCR certainty scaled by how many fields were found
    confidence: float


def extract_identity(engine: OcrEngine, image_bytes: bytes, today: date | None = None) -> Extraction:
    """Reads an ID photo and finds its identity fields. The same photo always gives the same answer."""
    boxes = engine.read(image_bytes)
    fields = parse_document(boxes, today)
    certainty = sum(box.score for box in boxes) / len(boxes) if boxes else 0.0
    return Extraction(fields, round(certainty * fields.found / _TOTAL_FIELDS, 3))
