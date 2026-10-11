import io
import shutil
from datetime import date

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw, ImageFont

from app.engine import OcrText, TesseractEngine, UnreadableImageError
from app.main import MAX_IMAGE_BYTES, Settings, create_app
from app.service import extract_identity

SECRET = "test-internal-secret"
AUTH = {"X-Internal-Secret": SECRET}
CEDULA_TEXT = "V 12.345.678\nAPELLIDOS\nGONZALEZ PEREZ\nNOMBRES\nMARIA FERNANDA\nF. NACIMIENTO 14/03/2008"


class FakeEngine:
    """Returns canned text per layout mode and records what it was asked."""

    def __init__(self, texts: dict[int, str], confidence: float = 0.9) -> None:
        self.texts = texts
        self.confidence = confidence
        self.modes: list[int] = []

    def read(self, image_bytes: bytes, page_segmentation_mode: int) -> OcrText:
        if not image_bytes.startswith(b"IMG"):
            raise UnreadableImageError("not an image")
        self.modes.append(page_segmentation_mode)
        return OcrText(self.texts.get(page_segmentation_mode, ""), self.confidence)


def client_with(engine: FakeEngine, secret: str = SECRET) -> TestClient:
    settings = Settings()
    settings.internal_secret = secret
    return TestClient(create_app(engine, settings))


def upload(client: TestClient, content: bytes = b"IMG", headers: dict | None = AUTH):
    return client.post("/extract", files={"file": ("id.jpg", content, "image/jpeg")}, headers=headers)


def test_returns_the_extracted_fields():
    response = upload(client_with(FakeEngine({6: CEDULA_TEXT})))

    assert response.status_code == 200
    assert response.json() == {
        "first_name": "Maria Fernanda",
        "last_name": "Gonzalez Perez",
        "document_number": "V-12345678",
        "birth_date": "2008-03-14",
        "confidence": 0.9,
        "engine": "tesseract",
    }


def test_an_unreadable_photo_yields_empty_fields_and_zero_confidence_not_an_error():
    response = upload(client_with(FakeEngine({})))

    assert response.status_code == 200
    assert response.json() == {
        "first_name": None,
        "last_name": None,
        "document_number": None,
        "birth_date": None,
        "confidence": 0.0,
        "engine": "tesseract",
    }


def test_confidence_drops_with_the_number_of_fields_found():
    response = upload(client_with(FakeEngine({6: "NOMBRES\nMARIA\nAPELLIDOS\nPEREZ"}, confidence=0.8)))

    assert response.json()["confidence"] == 0.4


def test_tries_a_second_layout_mode_only_when_the_first_finds_little():
    complete = FakeEngine({6: CEDULA_TEXT})
    extract_identity(complete, b"IMG", date(2026, 10, 10))
    assert complete.modes == [6]

    rescued = FakeEngine({6: "blurry noise", 11: CEDULA_TEXT})
    result = extract_identity(rescued, b"IMG", date(2026, 10, 10))
    assert rescued.modes == [6, 11]
    assert result.fields.found == 4


@pytest.mark.parametrize("headers", [None, {}, {"X-Internal-Secret": "wrong"}, {"X-Internal-Secret": ""}])
def test_rejects_callers_without_the_internal_secret(headers):
    engine = FakeEngine({6: CEDULA_TEXT})

    assert upload(client_with(engine), headers=headers).status_code == 401
    assert engine.modes == []


def test_lets_nobody_in_when_no_secret_is_configured():
    client = client_with(FakeEngine({6: CEDULA_TEXT}), secret="")

    assert upload(client, headers={"X-Internal-Secret": ""}).status_code == 401
    assert upload(client, headers=None).status_code == 401


def test_rejects_an_image_over_the_size_limit_without_reading_it():
    engine = FakeEngine({6: CEDULA_TEXT})

    response = upload(client_with(engine), content=b"IMG" + b"0" * MAX_IMAGE_BYTES)

    assert response.status_code == 413
    assert engine.modes == []


def test_rejects_a_file_that_is_not_an_image():
    assert upload(client_with(FakeEngine({})), content=b"<script>alert(1)</script>").status_code == 415


def test_requires_a_file():
    assert client_with(FakeEngine({})).post("/extract", headers=AUTH).status_code == 422


def test_health_check_needs_no_secret():
    assert client_with(FakeEngine({})).get("/healthz").json() == {"status": "ok"}


def test_never_exposes_interactive_docs():
    client = client_with(FakeEngine({}))

    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404


def render_id_card(lines: list[str]) -> bytes:
    """Draws a plain ID card, the way a clean photo of one would look."""
    image = Image.new("RGB", (1000, 630), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 34)
    for index, line in enumerate(lines):
        draw.text((60, 50 + index * 62), line, fill="black", font=font)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


needs_tesseract = pytest.mark.skipif(shutil.which("tesseract") is None, reason="Tesseract is not installed")


@needs_tesseract
def test_real_tesseract_reads_a_rendered_spanish_id_end_to_end():
    card = render_id_card(
        [
            "REPÚBLICA BOLIVARIANA DE VENEZUELA",
            "CÉDULA DE IDENTIDAD  V 12.345.678",
            "APELLIDOS",
            "GONZÁLEZ PÉREZ",
            "NOMBRES",
            "MARÍA FERNANDA",
            "F. NACIMIENTO 14/03/2008",
            "F. EXPEDICIÓN 02/05/2022",
        ]
    )
    settings = Settings()
    settings.internal_secret = SECRET
    client = TestClient(create_app(TesseractEngine("spa+eng"), settings))

    response = upload(client, content=card)

    assert response.status_code == 200
    body = response.json()
    assert body["document_number"] == "V-12345678"
    assert body["birth_date"] == "2008-03-14"
    # Accents are what the Spanish language data is for
    assert body["last_name"] == "González Pérez"
    assert body["first_name"] == "María Fernanda"
    assert body["confidence"] > 0.6


@needs_tesseract
def test_real_tesseract_finds_nothing_in_a_blank_photo():
    settings = Settings()
    settings.internal_secret = SECRET
    client = TestClient(create_app(TesseractEngine("spa+eng"), settings))
    blank = io.BytesIO()
    Image.new("RGB", (640, 400), (0, 128, 0)).save(blank, format="JPEG")

    body = upload(client, content=blank.getvalue()).json()

    assert body["first_name"] is None and body["document_number"] is None
    assert body["confidence"] == 0.0


@needs_tesseract
def test_real_engine_treats_a_tiny_image_as_unreadable_instead_of_failing():
    tiny = io.BytesIO()
    Image.new("RGB", (1, 1), "white").save(tiny, format="PNG")

    read = TesseractEngine("spa+eng").read(tiny.getvalue(), 6)

    assert read.text == ""
    assert read.confidence == 0.0


@needs_tesseract
def test_real_engine_rejects_bytes_that_are_not_an_image():
    with pytest.raises(UnreadableImageError):
        TesseractEngine("spa+eng").read(b"definitely not an image", 6)
