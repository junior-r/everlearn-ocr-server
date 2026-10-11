# Everlearn OCR server

## The Need

Onboarding needs the names, document number and birth date read from a photo of an ID document.

## The Goal

A small internal service that turns one image into those four fields, so the backend holds no OCR code or native dependencies.

## The Reason

- **Python + Tesseract.** Tesseract is free, runs offline (ID photos never leave our infrastructure), and ships Spanish language data; Python has its most mature bindings. EasyOCR was rejected for now: it pulls in PyTorch (a multi-gigabyte image) for accuracy we have not yet shown we need.
- **A separate service** keeps Tesseract and Pillow out of the NestJS image and lets OCR scale, or be replaced, on its own.
- **Parsing is pure.** `app/parser.py` and `app/mrz.py` work on text only, so the rules are tested without Tesseract.

## The Implementation

- `POST /extract` — multipart `file` (JPEG/PNG/WebP, max 5 MB), header `X-Internal-Secret`. Returns `first_name`, `last_name`, `document_number`, `birth_date` (ISO), `confidence` (0–1), `engine`.
- `GET /healthz` — liveness, no secret.
- **Pipeline:** `engine.py` (EXIF rotation, greyscale, upscale, contrast → Tesseract `spa+eng`) → `service.py` (page mode 6, then 11 if little was found) → `parser.py` (machine-readable zone first, with ICAO check digits; then printed labels such as `APELLIDOS` / `NOMBRES` / `F. NACIMIENTO`).
- **Unreadable photo:** `200` with every field `null` and `confidence: 0`. The applicant then types the data; only a file that is not an image is an error (`415`).
- **Security:** reachable only inside the Compose network (no published port). Without `INTERNAL_SERVICE_SECRET` configured it refuses every request. Images are not stored: Tesseract reads each one from a temporary file that is deleted right after, and nothing about its content is logged.
- **Config:** `INTERNAL_SERVICE_SECRET`, `OCR_LANGUAGES` (default `spa+eng`), `OCR_MAX_CONCURRENCY`.

## Running

```bash
docker compose up -d --build ocr-server                        # from the workspace root
docker build --target test -t everlearn-ocr-test ./ocr-server  # runs the tests
```

## Known gaps

- Tuned for Latin-American ID cards and passports with a machine-readable zone; other layouts may yield partial data.
- No deskewing or glare removal: a tilted or reflective photo reads poorly.
- Dependencies are version-ranged in `requirements.txt`, not locked.
