# Atlas crawler — Cloud Run Job, triggered weekly by Cloud Scheduler.
#
# Build context is the REPO ROOT, same reason as the orchestrator's
# Dockerfile: it imports its sibling `backend.orchestrator.llm`.
#
#   docker build -f backend/crawler/Dockerfile -t atlas-crawler .

FROM python:3.12-slim

WORKDIR /app

COPY backend/crawler/requirements.txt ./backend/crawler/requirements.txt
RUN pip install --no-cache-dir -r backend/crawler/requirements.txt

COPY backend/crawler ./backend/crawler
COPY backend/orchestrator/llm.py ./backend/orchestrator/llm.py
COPY backend/orchestrator/packs.py ./backend/orchestrator/packs.py
COPY backend/orchestrator/__init__.py ./backend/orchestrator/__init__.py
# llm.py imports backend.accessor.okf_loader (and packs.py above); both are
# import-time dependencies of the embedding helper the crawler uses, so they
# ship in this image too.
COPY backend/accessor ./backend/accessor
COPY backend/__init__.py ./backend/__init__.py

ENV PYTHONUNBUFFERED=1

ENTRYPOINT ["python", "-m", "backend.crawler.main"]
