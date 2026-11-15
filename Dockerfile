# syntax=docker/dockerfile:1
# Earth Verdict: one image serves the API and the built frontend.
#   docker compose up -d --build          run the service
#   docker compose --profile test run --rm backend-tests
#   docker compose --profile test run --rm e2e
ARG PYTHON_VERSION=3.13
ARG NODE_VERSION=22
ARG PLAYWRIGHT_VERSION=1.65.1

# ---- frontend dependencies -------------------------------------------------
FROM node:${NODE_VERSION}-slim AS web-deps
WORKDIR /repo/frontend
RUN corepack enable && corepack prepare pnpm@9.15.9 --activate
COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

# ---- frontend build (saved cases, events and trend layers are bundled) ------
FROM web-deps AS web
ARG VITE_DEFAULT_SOURCE=live
COPY data/cases /repo/data/cases
COPY data/events /repo/data/events
COPY data/layers /repo/data/layers
COPY frontend/ ./
RUN VITE_DEFAULT_SOURCE=${VITE_DEFAULT_SOURCE} pnpm build

# ---- API + static frontend --------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install -r backend/requirements.txt
COPY backend/ backend/
COPY data/cases data/cases
COPY data/events data/events
COPY data/layers data/layers
COPY data/cmip6 data/cmip6
COPY --from=web /repo/frontend/dist frontend/dist
# The disk cache is a volume; the app writes only there.
RUN useradd --uid 10001 --create-home ev && mkdir -p data/cache && chown ev data/cache
USER ev
EXPOSE 8790
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8790/health', timeout=4)"]
# One worker: rate limits and in-memory caches live in process memory.
CMD ["uvicorn", "app.main:app", "--app-dir", "backend", "--host", "0.0.0.0", "--port", "8790", \
     "--workers", "1", "--timeout-keep-alive", "30"]

# ---- backend tests (sources are faked; no keys needed) ----------------------
FROM app AS backend-tests
COPY tools/ tools/
COPY deploy/ deploy/
CMD ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider", "backend/tests"]

# ---- browser tests: Vite dev server + Playwright Chromium -------------------
FROM mcr.microsoft.com/playwright:v${PLAYWRIGHT_VERSION}-noble AS e2e
WORKDIR /repo/frontend
RUN npm install -g pnpm@9.15.9
COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY data/cases /repo/data/cases
COPY data/events /repo/data/events
COPY data/layers /repo/data/layers
COPY frontend/ ./
CMD ["npx", "playwright", "test", "--reporter=line"]
