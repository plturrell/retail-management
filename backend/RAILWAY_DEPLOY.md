# Deploying the RetailSG backend to Railway

The backend is a FastAPI / uvicorn app that builds from `backend/Dockerfile`.
It depends on:

- **Firestore** (Firebase Admin SDK) — primary data store.
- **TiDB Cloud** (MySQL-compatible) — additive ledger / analytics layer
  (optional during migration; the app still runs without it).
- Optional: Gemini, Document AI, Snowflake, Multica.

## 1. Create the service

1. Railway → **New Project** → **Deploy from GitHub repo** → pick this repo.
2. Service settings:
   - **Root Directory:** `backend`
   - **Builder:** Dockerfile (auto-detected)
   - **Start Command:**
     ```
     uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 1
     ```
     (Required — the Dockerfile hard-codes port 8000; Railway needs `$PORT`.
     Workers must stay at 1 — see §7.)
3. **Networking:** Generate Domain.

## 2. Required environment variables

Configure these in Railway → **Variables**. Never commit them to git.

| Key | Notes |
|---|---|
| `ENVIRONMENT` | `production` |
| `GCP_PROJECT_ID` | Firebase / GCP project id |
| `FIREBASE_PROJECT_ID` | Same as above |
| `GOOGLE_APPLICATION_CREDENTIALS_JSON` | Paste the **entire** Firebase service-account JSON as a single-line string. The app materialises it to a tmpfile at startup (see `app/firestore.py::_materialise_credentials_from_env`). Do **not** also set `GOOGLE_APPLICATION_CREDENTIALS`. |
| `CORS_ORIGINS` | JSON array, e.g. `["https://retailsg.app"]` |
| `TIDB_DATABASE_URL` | TiDB Cloud → Cluster → Connect → SQLAlchemy. Format: `mysql+asyncmy://<user>:<password>@<host>:4000/<db>?ssl=true` (TiDB Serverless requires TLS). Use a freshly-rotated key. |
| `TIDB_SSL_CA` | Usually unnecessary on Linux containers (system CA bundle covers TiDB Serverless). Set only if asyncmy can't verify the cert chain. |
| `GEMINI_API_KEY`, `DOCUMENT_AI_*`, `MULTICA_*`, `SNOWFLAKE_*` | Set only if those features are enabled in production. |

## 3. TiDB Cloud setup

1. **Rotate the public/private API key in TiDB Cloud** before doing anything
   else. Any key shared in chat / commits is compromised.
2. Cluster → **SQL** → run `CREATE DATABASE retailsg;` (one-time).
3. Cluster → **Connect** → **SQLAlchemy** → copy the connection string and
   paste into `TIDB_DATABASE_URL` (with the new key).
4. Apply migrations from your local machine the first time:
   ```bash
   cd backend
   pip install -r requirements.txt
   export TIDB_DATABASE_URL='<value from Railway, with the new key>'
   alembic upgrade head
   ```
   Subsequent migrations can run as a Railway deploy step (see §5).

## 4. Healthchecks

- Liveness: `GET /api/health` → returns `{"status":"healthy"}`.
- Readiness: `GET /api/health/ready` → pings Firestore.
- TiDB probe: `GET /api/health/tidb` → returns `disabled` / `ok` / `error`.

Set Railway's healthcheck path to `/api/health`.

## 5. Running migrations on deploy (optional)

Add a Railway *Pre-Deploy Command* or a separate **Migration** service:

```
alembic upgrade head
```

The app itself does **not** run migrations on startup, so a misconfigured
TiDB URL won't crash the API — `tidb.healthcheck()` will report the error.

## 6. What's intentionally not done yet

- **Mangle binary** (`tools/mangle/bin/mg`) — Linux build is a stub. Confirm
  whether anything in the production code path actually invokes it.
- **`alembic` directory** — now committed (`backend/alembic/`); the Dockerfile
  COPY for `alembic/` and `alembic.ini` is now satisfied.
- **TiDB integration tests** — the SQL layer ships without unit tests this
  iteration (per scoping). Plan: in-memory sqlite + ORM CRUD smoke tests.
- **Cutover** — the inventory ledger dual-writes; reads still come from
  Firestore. Switch reads to TiDB once we trust the data.

## 7. Worker concurrency

**The API runs with `--workers 1` and that's load-bearing.**

Two pieces of process-local state make multi-worker setups silently incorrect:

- **Idempotency cache** (`backend/app/idempotency.py`) — a module-level dict
  keyed by `(actor, scope, idempotency_key)`. Used by bulk price publish and
  similar write paths to absorb retries. With N workers, each worker has its
  own cache; a retry hashed to a different worker re-executes the work.
- **Rate limiter** (`backend/app/rate_limit.py`, SlowAPI in-memory backend) —
  per-IP buckets live in the worker's RAM. With N workers, each client's
  effective limit is ~Nx the documented cap.

**Scale horizontally, not vertically.** Cloud Run already does this via
container replicas (`max-instances=10` in `cloudbuild.yaml`); Railway does it
via service replicas. Both are correct because each replica owns its own
client cohort for the duration of the connection.

**Before raising `--workers` above 1**, both stores must move to a shared
backend:

- Idempotency: swap `_cache` / `_inflight_locks` in `idempotency.py` for a
  Firestore collection (TTL-indexed) or Redis with `SET NX EX`. Call sites
  don't change — they already use the `guard()` context manager.
- Rate limiter: pass `storage_uri="redis://..."` to `Limiter()` in
  `rate_limit.py` and add a Redis instance to the deploy.

A startup-time assertion (`if WORKERS != 1 in production: fail`) belongs in
`backend/app/config.py`'s `validate_production_config` once the in-flight
backend changes there are committed; until then, this doc is the guardrail.
