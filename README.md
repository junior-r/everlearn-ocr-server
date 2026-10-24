# Everlearn OCR server

## The Need

Onboarding needs the names, document number and birth date read from a photo of an ID document.

## The Goal

A small internal service that turns one image into those four fields, so the backend holds no OCR code or native dependencies.

## The Reason

- **RapidOCR (PaddleOCR models on ONNX Runtime).** Free (Apache-2.0), runs offline on the CPU (ID photos never leave our infrastructure), and reads phone photos of cards reliably. It replaced Tesseract, which is built for scanned pages: on a photographed card its single global threshold lost whole areas of print (dark text over the tinted coat of arms), so the same card gave different fields from photo to photo, and the multi-pass and fuzzy-label rules added to compensate made it worse. On seven real photos Tesseract got 15 of 28 fields; RapidOCR gets 28, in about 1 s each. EasyOCR and full PaddleOCR were rejected: they pull in PyTorch or Paddle (gigabytes) for no gain here.
- **Positions, not lines of text.** The engine returns each text with its box, so a value is found where it is printed beside its label, instead of guessing from a flattened text dump.
- **A separate service** keeps the models and native libraries out of the NestJS image and lets OCR scale, or be replaced, on its own.
- **Parsing is pure.** `app/layout.py`, `app/parser.py` and `app/mrz.py` work on boxes and text only, so the rules are tested without the models.

## The Implementation

- `POST /extract` — multipart `file` (JPEG/PNG/WebP, max 5 MB), header `X-Internal-Secret`. Returns `first_name`, `last_name`, `document_number`, `birth_date` (ISO), `confidence` (0–1), `engine` (`rapidocr`).
- `GET /healthz` — liveness, no secret.
- **Pipeline:** `engine.py` (decode, EXIF rotation → one RapidOCR read → text boxes) → `parser.py` → `service.py` (confidence: mean recognition score × share of the four fields found). One read per photo, so the same photo always gives the same answer.
- **Parsing:** the machine-readable zone first, trusted only with valid ICAO check digits. Otherwise each field comes from its label (`APELLIDOS`, `NOMBRES`, `F. NACIMIENTO`, `NUI`, `DNI`, ...): the value in the label's own box, else the nearest box to its right, then below (a value wrapping onto more lines is joined), and only when neither holds a valid value, the one above (Venezuelan cédulas print dates above their labels). A value must have the field's shape (name, date, number) and is never another label. Without a label, only a Venezuelan-format number (`V 12.345.678`) is taken. Nothing else is guessed: a missing field stays `null`.
- **Adding a country:** run the engine on a real photo, copy the boxes it returns into `tests/test_parser.py` with the personal data replaced, then add any new label until it parses. Never commit a real ID photo or real personal data.
- **Unreadable photo:** `200` with every field `null` and `confidence: 0`. The applicant then types the data; only a file that is not an image is an error (`415`).
- **Security:** reachable only inside the Compose network (no published port). Without `INTERNAL_SERVICE_SECRET` configured it refuses every request. Images are read in memory and never stored, and nothing about their content is logged. The models are downloaded when the image is built; the running service makes no outbound calls.
- **Config:** `INTERNAL_SERVICE_SECRET`, `OCR_MAX_CONCURRENCY`.

## Running

```bash
docker compose up -d --build ocr-server                        # from the workspace root
docker build --target test -t everlearn-ocr-test ./ocr-server  # runs the tests
```

## Known gaps

- Labels are known for Venezuelan and Ecuadorian cédulas, Spanish DNIs and passports (MRZ); another layout needs its labels added (see "Adding a country").
- No perspective correction: a card photographed at a steep angle may put a value out of line with its label.
- Dependencies are version-ranged in `requirements.txt`, not locked; the models are those RapidOCR downloads for its pinned major version.
