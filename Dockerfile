FROM node:24.20.0-bookworm-slim AS frontend-builder

WORKDIR /build

COPY package.json package-lock.json ./
RUN npm ci

COPY frontend ./frontend
RUN npm run build

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml ./
RUN python -m pip install --upgrade pip \
    && python -c "import subprocess, sys, tomllib; dependencies = tomllib.load(open('pyproject.toml', 'rb'))['project']['dependencies']; subprocess.check_call([sys.executable, '-m', 'pip', 'install', *dependencies])"

COPY --from=frontend-builder /build/app/web/static/tiptap-editor.js ./app/web/static/tiptap-editor.js
COPY --from=frontend-builder /build/app/web/static/tiptap-editor.css ./app/web/static/tiptap-editor.css

COPY scripts/docker-entrypoint.sh ./scripts/docker-entrypoint.sh

RUN chmod +x ./scripts/docker-entrypoint.sh

ENTRYPOINT ["./scripts/docker-entrypoint.sh"]
