# API image — build with context set to this directory:
#   docker compose build api   (from backend/)
#   gcloud builds submit --config=cloudbuild.yaml .   (from backend/)
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY alembic ./alembic
COPY alembic.ini .

# Mangle: tools/mangle/bin/mg is often macOS-only; keep stub for Linux (see root Dockerfile).
RUN echo "Mangle Linux stub deployed. Waiting for architectural binary." > /usr/local/bin/mg_linux_stub

EXPOSE 8000

# Single worker: the idempotency cache and SlowAPI rate limiter both live in
# process memory and are not shared across workers. Multiple workers would
# silently break idempotency on retries and let clients exceed rate limits
# by ~Nx. Scale horizontally via Cloud Run / Railway replicas instead, or
# move both stores to a shared backend (Redis / Firestore) before raising
# this. See backend/RAILWAY_DEPLOY.md §7.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
