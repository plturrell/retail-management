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
echo "  Next steps:"
echo "    1. Run: cd backend && cp .env.example .env"
echo "    2. Deploy: cd backend && gcloud builds submit --config=cloudbuild.yaml ."
echo ""
