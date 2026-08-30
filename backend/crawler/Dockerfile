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
COPY backend/orchestrator/__init__.py ./backend/orchestrator/__init__.py
COPY backend/__init__.py ./backend/__init__.py

ENV PYTHONUNBUFFERED=1

ENTRYPOINT ["python", "-m", "backend.crawler.main"]
