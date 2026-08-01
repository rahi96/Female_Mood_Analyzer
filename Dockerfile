# syntax=docker/dockerfile:1

FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    VENV_PATH=/opt/venv

WORKDIR /app

RUN python -m venv "$VENV_PATH" \
    && "$VENV_PATH/bin/pip" install --upgrade pip setuptools wheel

COPY requirements.txt ./
RUN "$VENV_PATH/bin/pip" install -r requirements.txt


FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    VENV_PATH=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

RUN adduser --disabled-password --gecos "" appuser

COPY --from=builder "$VENV_PATH" "$VENV_PATH"
COPY --chown=appuser:appuser . .

RUN mkdir -p data \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
