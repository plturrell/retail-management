FROM python:3.14-slim AS base

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Exclude secrets and dev files
RUN rm -f .env firebase-service-account.json

EXPOSE 8000

# Cloud Run sets PORT env var; default to 8000
ENV PORT=8000

# Production: use gunicorn with uvicorn workers
# Cloud Run sends SIGTERM for graceful shutdown
CMD exec uvicorn app.main:app \
    --host 0.0.0.0 \
    --port $PORT \
    --workers 2 \
    --timeout-keep-alive 30
