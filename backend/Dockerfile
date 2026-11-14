# Nexus Viewer backend (FastAPI). Build:  docker build -t nexus-viewer-backend backend/
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY app ./app
COPY scripts ./scripts

# local cache (used when Supabase is not configured); mount a volume here to keep it
RUN mkdir -p /app/.cache && useradd --create-home appuser && chown -R appuser /app
USER appuser

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/api/health', timeout=8).status==200 else 1)"
# Jobs are tracked in memory, so a single worker process is used (see PROJECT_EXPLAINED.md).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
