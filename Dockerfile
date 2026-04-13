# Monorepo API image — build from repository root:
#   docker build -t retailsg-api .
#
# For day-to-day backend work, prefer backend/Dockerfile with context backend/
# (used by backend/docker-compose.yml and backend/cloudbuild.yaml).

FROM python:3.14-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app
COPY backend/alembic ./alembic
COPY backend/alembic.ini .

RUN echo "Mangle Linux stub deployed. Waiting for architectural binary." > /usr/local/bin/mg_linux_stub

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
