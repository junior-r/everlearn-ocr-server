import io
from datetime import date

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw, ImageFont

from app.engine import RapidOcrEngine, UnreadableImageError
from app.layout import TextBox
from app.main import MAX_IMAGE_BYTES, Settings, create_app
from app.service import extract_identity

SECRET = "test-internal-secret"
AUTH = {"X-Internal-Secret": SECRET}


def line(text: str, top: float, score: float = 0.9) -> TextBox:
    return TextBox(text, 40, top, 40 + 16 * len(text), top + 30, score)


CEDULA = [
    line("V 12.345.678", 0),
    line("APELLIDOS", 40),
    line("GONZALEZ PEREZ", 72),
    line("NOMBRES", 120),
    line("MARIA FERNANDA", 152),
    line("F. NACIMIENTO 14/03/2008", 200),
]


class FakeEngine:
    """Returns canned boxes and records how many times it was asked to read."""

    def __init__(self, boxes: list[TextBox]) -> None:
        self.boxes = boxes
        self.reads = 0

    def read(self, image_bytes: bytes) -> list[TextBox]:
        if not image_bytes.startswith(b"IMG"):
            raise UnreadableImageError("not an image")
        self.reads += 1
        return self.boxes


def client_with(engine: FakeEngine, secret: str = SECRET) -> TestClient:
    settings = Settings()
    settings.internal_secret = secret
    return TestClient(create_app(engine, settings))


def upload(client: TestClient, content: bytes = b"IMG", headers: dict | None = AUTH):
    return client.post("/extract", files={"file": ("id.jpg", content, "image/jpeg")}, headers=headers)


def test_returns_the_extracted_fields():
    response = upload(client_with(FakeEngine(CEDULA)))

    assert response.status_code == 200
    assert response.json() == {
        "first_name": "Maria Fernanda",
        "last_name": "Gonzalez Perez",
        "document_number": "V-12345678",
        "birth_date": "2008-03-14",
        "confidence": 0.9,
        "engine": "rapidocr",
    }


def test_an_unreadable_photo_yields_empty_fields_and_zero_confidence_not_an_error():
    response = upload(client_with(FakeEngine([])))

    assert response.status_code == 200
    assert response.json() == {
        "first_name": None,
        "last_name": None,
        "document_number": None,
        "birth_date": None,
        "confidence": 0.0,
        "engine": "rapidocr",
    }


def test_confidence_drops_with_the_number_of_fields_found():
    engine = FakeEngine([line("NOMBRES MARIA", 0, 0.8), line("APELLIDOS PEREZ", 40, 0.8)])

    assert upload(client_with(engine)).json()["confidence"] == 0.4


def test_reads_the_photo_once():
    engine = FakeEngine(CEDULA)

    extract_identity(engine, b"IMG", date(2026, 10, 10))

    assert engine.reads == 1


@pytest.mark.parametrize("headers", [None, {}, {"X-Internal-Secret": "wrong"}, {"X-Internal-Secret": ""}])
def test_rejects_callers_without_the_internal_secret(headers):
    engine = FakeEngine(CEDULA)

    assert upload(client_with(engine), headers=headers).status_code == 401
    assert engine.reads == 0


def test_lets_nobody_in_when_no_secret_is_configured():
    client = client_with(FakeEngine(CEDULA), secret="")

    assert upload(client, headers={"X-Internal-Secret": ""}).status_code == 401
    assert upload(client, headers=None).status_code == 401


def test_rejects_an_image_over_the_size_limit_without_reading_it():
    engine = FakeEngine(CEDULA)

    response = upload(client_with(engine), content=b"IMG" + b"0" * MAX_IMAGE_BYTES)

    assert response.status_code == 413
    assert engine.reads == 0


def test_rejects_a_file_that_is_not_an_image():
    assert upload(client_with(FakeEngine([])), content=b"<script>alert(1)</script>").status_code == 415


def test_requires_a_file():
    assert client_with(FakeEngine([])).post("/extract", headers=AUTH).status_code == 422


def test_health_check_needs_no_secret():
    assert client_with(FakeEngine([])).get("/healthz").json() == {"status": "ok"}


def test_never_exposes_interactive_docs():
    client = client_with(FakeEngine([]))

    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404


def render_id_card(lines: list[str]) -> bytes:
    """Draws a plain ID card, the way a clean photo of one would look."""
    image = Image.new("RGB", (1000, 630), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 34)
    for index, text in enumerate(lines):
        draw.text((60, 50 + index * 62), text, fill="black", font=font)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.fixture(scope="module")
def real_client() -> TestClient:
    settings = Settings()
    settings.internal_secret = SECRET
    return TestClient(create_app(RapidOcrEngine(), settings))


def test_the_real_engine_reads_a_rendered_spanish_id_end_to_end(real_client):
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

    response = upload(real_client, content=card)

    assert response.status_code == 200
    body = response.json()
    assert body["document_number"] == "V-12345678"
    assert body["birth_date"] == "2008-03-14"
    assert body["last_name"] == "González Pérez"
    assert body["first_name"] == "María Fernanda"
    assert body["confidence"] > 0.8


def test_the_real_engine_gives_the_same_answer_every_time(real_client):
    card = render_id_card(["APELLIDOS GONZÁLEZ PÉREZ", "NOMBRES MARÍA FERNANDA", "V 12.345.678"])

    answers = [upload(real_client, content=card).json() for _ in range(3)]

    assert answers[0] == answers[1] == answers[2]


def test_the_real_engine_finds_nothing_in_a_blank_photo(real_client):
    blank = io.BytesIO()
    Image.new("RGB", (640, 400), (0, 128, 0)).save(blank, format="JPEG")

    body = upload(real_client, content=blank.getvalue()).json()

    assert body["first_name"] is None and body["document_number"] is None
    assert body["confidence"] == 0.0


def test_the_real_engine_treats_a_tiny_image_as_unreadable_instead_of_failing():
    tiny = io.BytesIO()
    Image.new("RGB", (1, 1), "white").save(tiny, format="PNG")

    assert RapidOcrEngine().read(tiny.getvalue()) == []


def test_the_real_engine_rejects_bytes_that_are_not_an_image():
    with pytest.raises(UnreadableImageError):
        RapidOcrEngine().read(b"definitely not an image")
