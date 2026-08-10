# hub — unified capstone service (single frontend app, build-time app selection)
# Build from the REPO ROOT context (needs shared/ and hub/):
#   docker build -f hub/Dockerfile -t claude-lab-hub .
#   docker build -f hub/Dockerfile --build-arg APPS=quake,market -t claude-lab-hub .

# Stage 1: unified frontend (Vite/React) — APPS selects which apps are bundled
FROM node:20-slim AS frontend
ARG APPS=quake,news,trend,market
WORKDIR /build
COPY hub/frontend/package*.json ./
RUN npm ci
COPY hub/frontend/ ./
RUN VITE_APPS=$APPS npm run build -- --outDir dist --emptyOutDir

# Stage 2: python service
FROM python:3.11-slim
WORKDIR /srv/hub/backend
COPY shared/ /srv/shared/
COPY hub/backend/requirements.txt ./
RUN pip install --no-cache-dir fastapi "uvicorn[standard]" httpx feedparser yfinance pykrx boto3 \
    && pip install --no-cache-dir -e /srv/shared
COPY hub/backend/app/ ./app/
COPY hub/fixtures/ /srv/hub/fixtures/
COPY --from=frontend /build/dist ./static/app/
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
