FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY docsync ./docsync

RUN pip install .

WORKDIR /github/workspace

ENTRYPOINT ["docsync"]
