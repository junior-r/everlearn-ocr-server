FROM python:3.13-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt ./
# Creating the engine once downloads its models into the image, so the service never needs the internet
RUN pip install --no-cache-dir -r requirements.txt \
    && python -c "from rapidocr import RapidOCR; RapidOCR()"
COPY app ./app

# Build with `--target test` to run the suite, including the tests that run the real models
FROM base AS test
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*
COPY requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements-dev.txt
COPY tests ./tests
RUN python -m pytest -q

FROM base AS prod
RUN useradd --create-home --uid 10001 app
USER app
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
