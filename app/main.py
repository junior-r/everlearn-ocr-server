"""HTTP API of the OCR service. Internal only: called by the NestJS backend."""

from __future__ import annotations

import asyncio
import hmac
import logging
import os
from typing import Annotated

from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from .engine import OcrEngine, TesseractEngine, UnreadableImageError
from .service import extract_identity

MAX_IMAGE_BYTES = 5 * 1024 * 1024
logger = logging.getLogger("ocr-server")


class Settings:
    def __init__(self) -> None:
        self.internal_secret = os.environ.get("INTERNAL_SERVICE_SECRET", "")
        self.languages = os.environ.get("OCR_LANGUAGES", "spa+eng")
        # OCR is CPU-bound: more simultaneous reads than cores only makes each one slower
        self.max_concurrency = int(os.environ.get("OCR_MAX_CONCURRENCY", os.cpu_count() or 2))


class ExtractionResponse(BaseModel):
    first_name: str | None
    last_name: str | None
    document_number: str | None
    # ISO calendar date (YYYY-MM-DD)
    birth_date: str | None
    confidence: float
    engine: str


def create_app(engine: OcrEngine | None = None, settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    engine = engine or TesseractEngine(settings.languages)
    limiter = asyncio.Semaphore(settings.max_concurrency)
    app = FastAPI(title="Everlearn OCR", docs_url=None, redoc_url=None, openapi_url=None)

    def require_internal_caller(
        x_internal_secret: Annotated[str | None, Header()] = None,
    ) -> None:
        # Fails closed: with no secret configured, nobody is let in
        expected = settings.internal_secret
        if not expected or not hmac.compare_digest(x_internal_secret or "", expected):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unauthorized")

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/extract", dependencies=[Depends(require_internal_caller)])
    async def extract(file: Annotated[UploadFile, File()]) -> ExtractionResponse:
        # Read one byte past the limit to tell "exactly at the limit" from "over it"
        image_bytes = await file.read(MAX_IMAGE_BYTES + 1)
        if len(image_bytes) > MAX_IMAGE_BYTES:
            raise HTTPException(413, "Image too large")
        async with limiter:
            try:
                result = await run_in_threadpool(extract_identity, engine, image_bytes)
            except UnreadableImageError as error:
                raise HTTPException(
                    status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Not a readable image"
                ) from error
        fields = result.fields
        # Identity data is never logged, only how much of it was found
        logger.info("extracted %d of 4 fields, confidence %.2f", fields.found, result.confidence)
        return ExtractionResponse(
            first_name=fields.first_name,
            last_name=fields.last_name,
            document_number=fields.document_number,
            birth_date=fields.birth_date.isoformat() if fields.birth_date else None,
            confidence=result.confidence,
            engine="tesseract",
        )

    return app


app = create_app()
