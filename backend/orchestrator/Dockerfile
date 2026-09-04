# Atlas orchestrator — Cloud Run service.
#
# Build context is the REPO ROOT (not this directory), because the
# orchestrator imports its sibling `backend/accessor` package:
#
#   docker build -f backend/orchestrator/Dockerfile -t atlas-orchestrator .
#
# The GitHub Actions workflow (.github/workflows/deploy-backend.yml) builds
# and deploys this exact way via Cloud Build.

FROM python:3.12-slim

WORKDIR /app

COPY backend/orchestrator/requirements.txt ./backend/orchestrator/requirements.txt
RUN pip install --no-cache-dir -r backend/orchestrator/requirements.txt

COPY backend/orchestrator ./backend/orchestrator
COPY backend/accessor ./backend/accessor
# access.py reads the crawler's target list to know every private dataset
# (use case D), even one with no hand-authored catalog doc yet.
COPY backend/crawler/__init__.py backend/crawler/targets.py ./backend/crawler/
COPY backend/__init__.py ./backend/__init__.py
COPY okf-catalog ./okf-catalog

ENV PYTHONUNBUFFERED=1 \
    ATLAS_OKF_CATALOG_ROOT=/app/okf-catalog \
    PORT=8080

EXPOSE 8080

# Cloud Run sets $PORT; uvicorn reads it via the shell form CMD below.
CMD exec uvicorn backend.orchestrator.main:app --host 0.0.0.0 --port ${PORT}
