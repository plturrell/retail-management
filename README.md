# RetailSG (retailmanagement)

Monorepo for **RetailSG**: FastAPI backend (`backend/`), SwiftUI iOS app (`apps/ios/`), GCP/Firebase config at the repo root, and **tools** for data pipelines and Mangle facts.

## Layout

| Path | Purpose |
|------|---------|
| [`backend/`](backend/) | RetailSG API (FastAPI, Alembic, tests) |
| [`apps/ios/`](apps/ios/) | Xcode project, app sources, unit/UI tests |
| [`tools/pipelines/`](tools/pipelines/) | OCR → Mangle → catalog CLIs; [`run_pipeline.sh`](tools/pipelines/run_pipeline.sh) |
| [`tools/scripts/`](tools/scripts/) | GCP setup, PDF→Mangle, sales ledger Vertex pipeline |
| [`tools/mangle/bin/mg`](tools/mangle/bin/mg) | Mangle engine binary (macOS/ARM64 in repo; use a Linux build in containers—see Dockerfiles) |
| [`data/images/`](data/images/) | Source images for OCR (pipeline input) |
| [`data/ocr_outputs/`](data/ocr_outputs/) | JSON from OCR (generated, gitignored) |
| [`data/mangle_facts/`](data/mangle_facts/) | Generated `.mangle` fact files (gitignored) |
| [`data/catalog/`](data/catalog/) | Product images, embeddings index, `.npy` vectors |
| [`data/mangle/`](data/mangle/) | Checked-in example/query `.mangle` sources |
| [`docs/`](docs/) | Excel/PDF inputs referenced by pipelines |

## Requirements

- **Backend:** Python **3.14+** (matches [`Dockerfile`](Dockerfile) / [`backend/Dockerfile`](backend/Dockerfile))
- **iOS:** Xcode — open [`apps/ios/retailmanagement.xcodeproj`](apps/ios/retailmanagement.xcodeproj)
- **Local database (optional):** PostgreSQL 15, or Docker Compose below

## Backend API

Configuration is loaded from environment variables and optional `backend/.env`. Copy [`backend/.env.example`](backend/.env.example) to `backend/.env` and adjust values.

### Run with Uvicorn (local)

```bash
cd backend
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
export DATABASE_URL="postgresql+asyncpg://USER:PASS@localhost:5432/DBNAME"
alembic upgrade head
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Run with Docker Compose (Postgres + API)

Build context is **`backend/`** (see [`backend/docker-compose.yml`](backend/docker-compose.yml) and [`backend/Dockerfile`](backend/Dockerfile)):

```bash
cd backend
cp .env.example .env   # edit as needed
docker compose up
```

The API is exposed on port **8000**.

### API image from monorepo root

```bash
docker build -t retailsg-api .
```

### Tests

```bash
cd backend
source .venv/bin/activate
pip install -r requirements.txt
export DATABASE_URL="${DATABASE_URL:-postgresql+asyncpg://retailsg:retailsg@127.0.0.1:5432/retailsg}"
pytest
```

Tests use an in-memory SQLite database via overrides in [`backend/tests/conftest.py`](backend/tests/conftest.py); `DATABASE_URL` must still be a **valid URL string** so `app.database` can initialize at import time.

### Deploy (GCP)

See [`backend/cloudbuild.yaml`](backend/cloudbuild.yaml) for Cloud Build → Cloud Run:

```bash
cd backend && gcloud builds submit --config=cloudbuild.yaml .
```

### Local cache pressure

Build tools can fill the small local volume quickly. Use an external cache root
when available and clean generated outputs with:

```bash
CACHE_ROOT=/Volumes/ExternalCache/retailmanagement tools/scripts/clean_local_caches.sh --setup-env
tools/scripts/clean_local_caches.sh
```

See [`docs/local-cache-and-object-storage.md`](docs/local-cache-and-object-storage.md)
for npm, pip, Gradle, Homebrew, Firebase emulator, and Xcode DerivedData settings.

## Data pipeline (Gemini / Mangle)

From the **repository root**:

```bash
export GEMINI_API_KEY="your_key"
./tools/pipelines/run_pipeline.sh
```

Pipeline steps may write temporary local outputs under `data/ocr_outputs/`,
`data/mangle_facts/`, and `data/catalog/`. Durable OCR/AI artifacts should live
in `gs://victoriaensoapp-ai-artifacts`; see
[`docs/local-cache-and-object-storage.md`](docs/local-cache-and-object-storage.md).
Paths are resolved from [`tools/pipelines/paths.py`](tools/pipelines/paths.py)
(no hardcoded home directories).

Other CLIs (run from repo root with `python3 tools/pipelines/…` or `python3 tools/scripts/…`):

- **Excel → Mangle:** `tools/pipelines/excel_to_mangle.py` (defaults: `docs/` → `data/mangle_facts/`)
- **Shopify:** `tools/pipelines/shopify_connector.py`
- **GCP install script:** `tools/pipelines/install_gcloud.sh`
- **One-shot GCP resources:** `tools/scripts/gcp_setup.sh`

## iOS app

Open [`apps/ios/retailmanagement.xcodeproj`](apps/ios/retailmanagement.xcodeproj) in Xcode. Unit tests: `apps/ios/retailmanagementTests/`; UI tests: `apps/ios/retailmanagementUITests/`.

## CI

GitHub Actions runs backend `pytest` on push and pull requests (see [`.github/workflows/ci.yml`](.github/workflows/ci.yml)).
