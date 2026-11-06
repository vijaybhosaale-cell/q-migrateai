# One image runs both the AI engine (FastAPI, port 8002) and the cloud simulator (FastAPI, port 8001).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 QM_DATA_DIR=/app/data
WORKDIR /app

COPY requirements.txt requirements-postgres.txt ./
RUN pip install -r requirements-postgres.txt

COPY qmigrate ./qmigrate
COPY web/dist ./web/dist

# Run as an unprivileged user.
RUN useradd --system --uid 10001 qmigrate && mkdir -p /app/data && chown qmigrate /app/data
USER qmigrate

EXPOSE 8002
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8002/api/health', timeout=4).status == 200 else 1)"
# One worker: sessions, rate limits and the model cache live in this process.
CMD ["uvicorn", "qmigrate.server.app:app", "--host", "0.0.0.0", "--port", "8002", "--workers", "1"]
