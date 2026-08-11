# hub — unified capstone service (single frontend app, build-time app selection)
# Build from the REPO ROOT context (needs shared/ and hub/):
#   docker build -f hub/Dockerfile -t claude-lab-hub .
#   docker build -f hub/Dockerfile --build-arg APPS=quake,market -t claude-lab-hub .

# Stage 1: unified frontend (Vite/React, pnpm) — APPS selects which apps are bundled
FROM node:24-slim AS frontend
ARG APPS=quake,news,trend,market,contrail,wake
RUN corepack enable && corepack prepare pnpm@latest --activate
WORKDIR /build
COPY hub/frontend/package.json hub/frontend/pnpm-lock.yaml hub/frontend/pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY hub/frontend/ ./
RUN VITE_APPS=$APPS pnpm build --outDir dist --emptyOutDir

# Stage 2: python service (uv)
FROM python:3.11-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/
WORKDIR /srv/hub/backend
COPY shared/ /srv/shared/
COPY hub/backend/pyproject.toml hub/backend/uv.lock ./
RUN uv sync --frozen --no-dev
COPY hub/backend/app/ ./app/
COPY hub/fixtures/ /srv/hub/fixtures/
COPY --from=frontend /build/dist ./static/app/
EXPOSE 8000
CMD ["uv", "run", "--no-sync", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
