FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY app ./app
COPY migrations ./migrations
COPY alembic.ini ./
COPY scripts/docker-entrypoint.sh ./scripts/docker-entrypoint.sh

RUN python -m pip install --upgrade pip \
    && python -m pip install . \
    && chmod +x ./scripts/docker-entrypoint.sh

ENTRYPOINT ["./scripts/docker-entrypoint.sh"]
