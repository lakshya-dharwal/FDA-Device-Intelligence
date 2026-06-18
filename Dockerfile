# ── FDA Device Intelligence API — production image for GCP Cloud Run ──────────
FROM python:3.11-slim

# Don't write .pyc files; flush stdout/stderr immediately for clean Cloud logs.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install dependencies first so this layer is cached when only source changes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source.
COPY src/ ./src/

# Cloud Run injects the PORT env var (defaults to 8080) and routes to it.
ENV PORT=8080
EXPOSE 8080

# Shell form so ${PORT} is expanded at runtime; exec so uvicorn is PID 1
# and receives SIGTERM cleanly on Cloud Run scale-down.
CMD exec uvicorn src.backend.main:app --host 0.0.0.0 --port ${PORT}
