#!/usr/bin/env bash
set -euo pipefail

# ─── GCP Project Setup for RetailSG ──────────────────────────
# Project: project-b41c0c0d-6eea-4e9d-a78 (561509133799)
#
# Run this once to configure all GCP resources.
# Prerequisites: gcloud CLI installed and authenticated.
# ──────────────────────────────────────────────────────────────

PROJECT_ID="project-b41c0c0d-6eea-4e9d-a78"
REGION="asia-southeast1"
DB_INSTANCE="retailsg"
DB_NAME="retailsg"
DB_USER="retailsg"
SERVICE_ACCOUNT="retailsg-api"

echo "═══════════════════════════════════════════════════════"
echo "  RetailSG — GCP Setup"
echo "  Project: $PROJECT_ID"
echo "═══════════════════════════════════════════════════════"

# Set the active project
gcloud config set project "$PROJECT_ID"
echo "✔ Active project set to $PROJECT_ID"

# ─── Enable Required APIs ────────────────────────────────────
echo ""
echo "▶ Enabling GCP APIs..."
gcloud services enable \
    cloudbuild.googleapis.com \
    run.googleapis.com \
    sqladmin.googleapis.com \
    secretmanager.googleapis.com \
    artifactregistry.googleapis.com \
    firebase.googleapis.com \
    identitytoolkit.googleapis.com \
    aiplatform.googleapis.com \
    generativelanguage.googleapis.com \
    --quiet
echo "  ✔ APIs enabled"

# ─── Artifact Registry ───────────────────────────────────────
echo ""
echo "▶ Creating Artifact Registry repo..."
gcloud artifacts repositories create retailsg \
    --repository-format=docker \
    --location="$REGION" \
    --description="RetailSG container images" \
    --quiet 2>/dev/null || echo "  (already exists)"
echo "  ✔ Artifact Registry ready"

# ─── Cloud SQL ────────────────────────────────────────────────
echo ""
echo "▶ Creating Cloud SQL instance (this takes ~5 minutes)..."
if gcloud sql instances describe "$DB_INSTANCE" --quiet 2>/dev/null; then
    echo "  (instance already exists)"
else
    gcloud sql instances create "$DB_INSTANCE" \
        --database-version=POSTGRES_15 \
        --tier=db-f1-micro \
        --region="$REGION" \
        --storage-type=SSD \
        --storage-size=10GB \
        --availability-type=zonal \
        --quiet
fi
echo "  ✔ Cloud SQL instance ready"

echo "▶ Creating database and user..."
gcloud sql databases create "$DB_NAME" \
    --instance="$DB_INSTANCE" --quiet 2>/dev/null || echo "  (database exists)"

DB_PASSWORD=$(openssl rand -base64 24)
gcloud sql users create "$DB_USER" \
    --instance="$DB_INSTANCE" \
    --password="$DB_PASSWORD" --quiet 2>/dev/null || echo "  (user exists — password unchanged)"
echo "  ✔ Database: $DB_NAME, User: $DB_USER"

# ─── Service Account ─────────────────────────────────────────
echo ""
echo "▶ Creating service account..."
gcloud iam service-accounts create "$SERVICE_ACCOUNT" \
    --display-name="RetailSG API Service Account" \
    --quiet 2>/dev/null || echo "  (already exists)"

SA_EMAIL="${SERVICE_ACCOUNT}@${PROJECT_ID}.iam.gserviceaccount.com"

# Grant roles
for ROLE in roles/cloudsql.client roles/secretmanager.secretAccessor roles/firebase.admin; do
    gcloud projects add-iam-policy-binding "$PROJECT_ID" \
        --member="serviceAccount:$SA_EMAIL" \
        --role="$ROLE" \
        --quiet > /dev/null
done
echo "  ✔ Service account: $SA_EMAIL"

# ─── Secret Manager ──────────────────────────────────────────
echo ""
echo "▶ Storing secrets..."

# Database URL
CLOUD_SQL_CONNECTION="${PROJECT_ID}:${REGION}:${DB_INSTANCE}"
DB_URL="postgresql+asyncpg://${DB_USER}:${DB_PASSWORD}@/${DB_NAME}?host=/cloudsql/${CLOUD_SQL_CONNECTION}"
echo -n "$DB_URL" | gcloud secrets create retailsg-db-url \
    --data-file=- --quiet 2>/dev/null || \
    echo -n "$DB_URL" | gcloud secrets versions add retailsg-db-url --data-file=- --quiet
echo "  ✔ Secret: retailsg-db-url"

# ─── Firebase Auth Setup ──────────────────────────────────────
echo ""
echo "▶ Initializing Firebase Auth (Identity Platform)..."
ACCESS_TOKEN=$(gcloud auth print-access-token)

# Initialize Identity Platform
curl -s -X POST \
    "https://identitytoolkit.googleapis.com/v2/projects/${PROJECT_ID}/identityPlatform:initializeAuth" \
    -H "Authorization: Bearer $ACCESS_TOKEN" \
    -H "Content-Type: application/json" \
    -H "X-Goog-User-Project: $PROJECT_ID" \
    -d '{}' > /dev/null 2>&1 || true

# Enable Email/Password sign-in
curl -s -X PATCH \
    "https://identitytoolkit.googleapis.com/v2/projects/${PROJECT_ID}/config?updateMask=signIn.email" \
    -H "Authorization: Bearer $ACCESS_TOKEN" \
    -H "Content-Type: application/json" \
    -H "X-Goog-User-Project: $PROJECT_ID" \
    -d '{"signIn":{"email":{"enabled":true,"passwordRequired":true}}}' > /dev/null
echo "  ✔ Firebase Auth: Email/Password sign-in enabled"

# Note: No SA key needed — Cloud Run uses Workload Identity
echo "  ℹ  Using Workload Identity (no SA key file needed)"

# ─── Snowflake Secrets ────────────────────────────────────────
echo ""
echo "▶ Storing Snowflake secrets in Secret Manager..."

# Snowflake account identifier (not sensitive — store for convenience)
echo -n "NDKTJHV-MH65474" | gcloud secrets create retailsg-snowflake-account \
    --data-file=- --quiet 2>/dev/null || \
    echo -n "NDKTJHV-MH65474" | gcloud secrets versions add retailsg-snowflake-account --data-file=- --quiet
echo "  ✔ Secret: retailsg-snowflake-account"

# Snowflake user
echo -n "RETAILSG_SVC" | gcloud secrets create retailsg-snowflake-user \
    --data-file=- --quiet 2>/dev/null || \
    echo -n "RETAILSG_SVC" | gcloud secrets versions add retailsg-snowflake-user --data-file=- --quiet
echo "  ✔ Secret: retailsg-snowflake-user"

# Snowflake password — prompt securely (must match what you set in setup_snowflake.sql)
echo ""
echo "  ┌───────────────────────────────────────────────────────┐"
echo "  │  Enter the RETAILSG_SVC password you set in           │"
echo "  │  scripts/setup_snowflake.sql (default: Rsg#Live2026!) │"
echo "  └───────────────────────────────────────────────────────┘"
read -rsp "  Snowflake password: " SF_PASSWORD
echo ""
echo -n "$SF_PASSWORD" | gcloud secrets create retailsg-snowflake-password \
    --data-file=- --quiet 2>/dev/null || \
    echo -n "$SF_PASSWORD" | gcloud secrets versions add retailsg-snowflake-password --data-file=- --quiet
echo "  ✔ Secret: retailsg-snowflake-password"
unset SF_PASSWORD

# Static config values
echo -n "RETAILSG"       | gcloud secrets create retailsg-snowflake-database  --data-file=- --quiet 2>/dev/null || \
    echo -n "RETAILSG"   | gcloud secrets versions add retailsg-snowflake-database  --data-file=- --quiet
echo -n "ANALYTICS"      | gcloud secrets create retailsg-snowflake-schema    --data-file=- --quiet 2>/dev/null || \
    echo -n "ANALYTICS"  | gcloud secrets versions add retailsg-snowflake-schema    --data-file=- --quiet
echo -n "RETAILSG_WH"    | gcloud secrets create retailsg-snowflake-warehouse  --data-file=- --quiet 2>/dev/null || \
    echo -n "RETAILSG_WH"| gcloud secrets versions add retailsg-snowflake-warehouse  --data-file=- --quiet
echo -n "RETAILSG_ROLE"  | gcloud secrets create retailsg-snowflake-role      --data-file=- --quiet 2>/dev/null || \
    echo -n "RETAILSG_ROLE"| gcloud secrets versions add retailsg-snowflake-role      --data-file=- --quiet
echo -n "ETL"            | gcloud secrets create retailsg-snowflake-etl-schema --data-file=- --quiet 2>/dev/null || \
    echo -n "ETL"        | gcloud secrets versions add retailsg-snowflake-etl-schema --data-file=- --quiet

echo "  ✔ Snowflake config secrets stored"

# Grant the service account access to all Snowflake secrets
for SECRET in retailsg-snowflake-account retailsg-snowflake-user retailsg-snowflake-password \
              retailsg-snowflake-database retailsg-snowflake-schema retailsg-snowflake-warehouse \
              retailsg-snowflake-role retailsg-snowflake-etl-schema; do
    gcloud secrets add-iam-policy-binding "$SECRET" \
        --member="serviceAccount:$SA_EMAIL" \
        --role="roles/secretmanager.secretAccessor" \
        --quiet > /dev/null
done
echo "  ✔ Service account granted access to all Snowflake secrets"

# ─── Cloud Scheduler — Nightly ETL ───────────────────────────
echo ""
echo "▶ Setting up Cloud Scheduler for nightly ETL..."

# Enable Cloud Scheduler API
gcloud services enable cloudscheduler.googleapis.com --quiet

# Cloud Run service URL (available after first deploy)
CLOUD_RUN_URL="https://${_SERVICE_NAME:-retailsg-api}-$(gcloud run services describe "${_SERVICE_NAME:-retailsg-api}" \
    --region="$REGION" --format='value(status.url)' 2>/dev/null | sed 's|https://||' | cut -d. -f2-)"
# Fallback: construct URL pattern (will be correct after first deploy)
CLOUD_RUN_URL=$(gcloud run services describe "retailsg-api" \
    --region="$REGION" --format='value(status.url)' 2>/dev/null || echo "https://retailsg-api-HASH-as.a.run.app")

# Create or update the nightly ETL job
# Runs at 2:00 AM SGT = 18:00 UTC
if gcloud scheduler jobs describe retailsg-nightly-etl --location="$REGION" --quiet 2>/dev/null; then
    gcloud scheduler jobs update http retailsg-nightly-etl \
        --location="$REGION" \
        --schedule="0 18 * * *" \
        --uri="${CLOUD_RUN_URL}/api/etl/run" \
        --http-method=POST \
        --headers="Content-Type=application/json" \
        --oidc-service-account-email="$SA_EMAIL" \
        --time-zone="UTC" \
        --quiet
else
    gcloud scheduler jobs create http retailsg-nightly-etl \
        --location="$REGION" \
        --schedule="0 18 * * *" \
        --uri="${CLOUD_RUN_URL}/api/etl/run" \
        --http-method=POST \
        --headers="Content-Type=application/json" \
        --oidc-service-account-email="$SA_EMAIL" \
        --time-zone="UTC" \
        --description="Nightly PostgreSQL → Snowflake ETL (2am SGT)" \
        --quiet
fi
echo "  ✔ Cloud Scheduler: retailsg-nightly-etl (0 18 * * * UTC = 2am SGT)"

# Grant Cloud Scheduler permission to invoke the Cloud Run service
gcloud run services add-iam-policy-binding "retailsg-api" \
    --region="$REGION" \
    --member="serviceAccount:$SA_EMAIL" \
    --role="roles/run.invoker" \
    --quiet 2>/dev/null || true
echo "  ✔ Scheduler can invoke Cloud Run"

# ─── Summary ──────────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════════"
echo "  ✅ GCP Setup Complete!"
echo "═══════════════════════════════════════════════════════"
echo ""
echo "  Project:          $PROJECT_ID"
echo "  Region:           $REGION"
echo "  Cloud SQL:        $DB_INSTANCE ($REGION)"
echo "  Service Account:  $SA_EMAIL"
echo "  Database URL:     (stored in Secret Manager)"
echo ""
echo "  Snowflake:        NDKTJHV-MH65474.snowflakecomputing.com"
echo "  SF User:          RETAILSG_SVC"
echo "  SF Warehouse:     RETAILSG_WH"
echo "  SF Database:      RETAILSG  (ANALYTICS + ETL schemas)"
echo "  SF Password:      (stored in Secret Manager: retailsg-snowflake-password)"
echo ""
echo "  ETL Schedule:     Nightly 2am SGT via Cloud Scheduler"
echo ""
echo "  Next steps:"
echo "    1. Run Snowflake bootstrap:"
echo "       Open Snowsight → run scripts/setup_snowflake.sql as VICTORIAENSO"
echo "    2. Run Snowflake DDL (as RETAILSG_SVC):"
echo "       snowflake/schema/001_dimensions.sql"
echo "       snowflake/schema/002_facts.sql"
echo "       snowflake/schema/003_cortex_views.sql"
echo "    3. Deploy API:"
echo "       cd backend && gcloud builds submit --config=cloudbuild.yaml ."
echo "    4. Trigger first ETL:"
echo "       curl -X POST https://<YOUR_CLOUD_RUN_URL>/api/etl/run"
echo ""
