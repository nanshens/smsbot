FROM node:22-bookworm-slim AS frontend
WORKDIR /build/frontend
RUN corepack enable && corepack prepare pnpm@10.12.4 --activate
COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY frontend/ ./
RUN pnpm build

FROM python:3.13-slim-bookworm AS wheels
WORKDIR /build
# psycopg2 needs libc headers (including assert.h), not just the gcc executable.
RUN apt-get update && apt-get install -y --no-install-recommends build-essential libpq-dev && rm -rf /var/lib/apt/lists/*
COPY backend/requirements.lock ./requirements.lock
RUN pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.lock

FROM python:3.13-slim-bookworm
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/app/backend
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends nginx supervisor libpq5 ca-certificates && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 smsbot \
    && mkdir -p /var/lib/nginx /var/log/nginx /run/nginx \
    && chown -R smsbot:smsbot /var/lib/nginx /var/log/nginx /run/nginx
COPY --from=wheels /wheels /wheels
COPY backend/requirements.lock /app/backend/requirements.lock
RUN pip install --no-cache-dir --no-index --find-links=/wheels -r /app/backend/requirements.lock && rm -rf /wheels
COPY backend/ /app/backend/
COPY deploy/ /app/deploy/
COPY --from=frontend /build/frontend/dist /app/frontend/dist
USER smsbot
EXPOSE 8080 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3)"
CMD ["python", "-m", "app.start"]
