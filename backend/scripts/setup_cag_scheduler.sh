#!/usr/bin/env bash
# Idempotent setup for the NEC CAG every-3h Cloud Scheduler → Cloud Run OIDC push.
#
# Provisions (or refreshes) three things:
#   1. Service account `cag-scheduler@<PROJECT>.iam.gserviceaccount.com`
#   2. IAM binding: the SA gets `roles/run.invoker` on the retailsg-api service
#      so Cloud Scheduler's OIDC token is accepted at the Cloud Run edge.
#   3. Cloud Scheduler job `nec-cag-3h-push` posting to
#      `<CLOUD_RUN_URL>/api/cag/export/push/scheduled` every 3 hours, with
#      OIDC auth using the SA above and audience = the Cloud Run URL.
#
# Re-running this script is safe — every step is `describe || create` /
# `update`-style, so it converges on the desired state.
#
# Usage:
#   PROJECT_ID=victoriaenso REGION=asia-southeast1 \
#       ./backend/scripts/setup_cag_scheduler.sh
#
# When USE_FIRESTORE_CONFIG=1 (default) and the backend Python env is importable,
# the script will best-effort read scheduler_cron / scheduler_enabled from the
# Firestore-backed CAG config and use those values, so cron changes made from the
# staff portal UI are picked up on the next provisioning run. Set
# USE_FIRESTORE_CONFIG=0 to skip the Firestore probe and rely on env vars only.

set -euo pipefail

PROJECT_ID="${PROJECT_ID:?PROJECT_ID required}"
REGION="${REGION:-asia-southeast1}"
SERVICE_NAME="${SERVICE_NAME:-retailsg-api}"
SCHEDULER_SA_NAME="${SCHEDULER_SA_NAME:-cag-scheduler}"
SCHEDULER_SA_EMAIL="${SCHEDULER_SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
JOB_NAME="${JOB_NAME:-nec-cag-3h-push}"
SCHEDULE="${SCHEDULE:-0 */3 * * *}"
TIMEZONE="${TIMEZONE:-Asia/Singapore}"
USE_FIRESTORE_CONFIG="${USE_FIRESTORE_CONFIG:-1}"
SCHEDULER_ENABLED="yes"

# Best-effort Firestore probe — pulls scheduler_cron + scheduler_enabled from the
# CAG config doc. Failure is non-fatal: env defaults win. We export the values
# via two well-known lines on stdout so the bash side stays simple.
if [[ "${USE_FIRESTORE_CONFIG}" == "1" ]]; then
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    BACKEND_DIR="$(dirname "${SCRIPT_DIR}")"
    if PROBE_OUT="$(cd "${BACKEND_DIR}" && python - <<'PY' 2>/dev/null
from app.firestore import get_firestore_db
from app.services import cag_config
cfg = cag_config.load_config(get_firestore_db())
print(f"CRON={cfg.scheduler_cron or ''}")
print(f"ENABLED={'yes' if cfg.scheduler_enabled else 'no'}")
PY
    )"; then
        FIRESTORE_CRON="$(printf '%s\n' "${PROBE_OUT}" | sed -n 's/^CRON=//p')"
        FIRESTORE_ENABLED="$(printf '%s\n' "${PROBE_OUT}" | sed -n 's/^ENABLED=//p')"
        if [[ -n "${FIRESTORE_CRON}" ]]; then
            echo "✓ Firestore override: scheduler_cron='${FIRESTORE_CRON}'"
            SCHEDULE="${FIRESTORE_CRON}"
        fi
        if [[ -n "${FIRESTORE_ENABLED}" ]]; then
            SCHEDULER_ENABLED="${FIRESTORE_ENABLED}"
            echo "✓ Firestore override: scheduler_enabled='${SCHEDULER_ENABLED}'"
        fi
    else
        echo "ℹ Firestore probe skipped (backend Python env not available)"
    fi
fi

echo "▶ project=${PROJECT_ID} region=${REGION} service=${SERVICE_NAME}"
echo "▶ scheduler SA=${SCHEDULER_SA_EMAIL} job=${JOB_NAME} schedule='${SCHEDULE}'"

# 1. Service account ----------------------------------------------------------
if ! gcloud iam service-accounts describe "${SCHEDULER_SA_EMAIL}" \
        --project="${PROJECT_ID}" >/dev/null 2>&1; then
    echo "▶ creating service account ${SCHEDULER_SA_EMAIL}"
    gcloud iam service-accounts create "${SCHEDULER_SA_NAME}" \
        --project="${PROJECT_ID}" \
        --display-name="Cloud Scheduler — NEC CAG 3h push"
else
    echo "✓ service account ${SCHEDULER_SA_EMAIL} already exists"
fi

# 2. Resolve Cloud Run URL ----------------------------------------------------
CLOUD_RUN_URL="$(gcloud run services describe "${SERVICE_NAME}" \
    --project="${PROJECT_ID}" --region="${REGION}" \
    --format='value(status.url)')"
if [[ -z "${CLOUD_RUN_URL}" ]]; then
    echo "✗ could not resolve Cloud Run URL for ${SERVICE_NAME} in ${REGION}" >&2
    exit 1
fi
echo "✓ Cloud Run URL: ${CLOUD_RUN_URL}"

# 3. Grant run.invoker --------------------------------------------------------
echo "▶ ensuring roles/run.invoker on ${SERVICE_NAME} for ${SCHEDULER_SA_EMAIL}"
gcloud run services add-iam-policy-binding "${SERVICE_NAME}" \
    --project="${PROJECT_ID}" --region="${REGION}" \
    --member="serviceAccount:${SCHEDULER_SA_EMAIL}" \
    --role="roles/run.invoker" >/dev/null

# 4. Cloud Scheduler job ------------------------------------------------------
TARGET_URI="${CLOUD_RUN_URL}/api/cag/export/push/scheduled"
AUDIENCE="${CLOUD_RUN_URL}"

if gcloud scheduler jobs describe "${JOB_NAME}" \
        --project="${PROJECT_ID}" --location="${REGION}" >/dev/null 2>&1; then
    echo "▶ updating existing scheduler job ${JOB_NAME}"
    gcloud scheduler jobs update http "${JOB_NAME}" \
        --project="${PROJECT_ID}" --location="${REGION}" \
        --schedule="${SCHEDULE}" \
        --time-zone="${TIMEZONE}" \
        --http-method=POST \
        --uri="${TARGET_URI}" \
        --headers="Content-Type=application/json" \
        --message-body='{}' \
        --oidc-service-account-email="${SCHEDULER_SA_EMAIL}" \
        --oidc-token-audience="${AUDIENCE}"
else
    echo "▶ creating scheduler job ${JOB_NAME}"
    gcloud scheduler jobs create http "${JOB_NAME}" \
        --project="${PROJECT_ID}" --location="${REGION}" \
        --schedule="${SCHEDULE}" \
        --time-zone="${TIMEZONE}" \
        --http-method=POST \
        --uri="${TARGET_URI}" \
        --headers="Content-Type=application/json" \
        --message-body='{}' \
        --oidc-service-account-email="${SCHEDULER_SA_EMAIL}" \
        --oidc-token-audience="${AUDIENCE}"
fi

# 5. Honour scheduler_enabled toggle from the UI ----------------------------
if [[ "${SCHEDULER_ENABLED}" == "no" ]]; then
    echo "▶ scheduler_enabled=no — pausing job ${JOB_NAME}"
    gcloud scheduler jobs pause "${JOB_NAME}" \
        --project="${PROJECT_ID}" --location="${REGION}" >/dev/null
else
    echo "▶ scheduler_enabled=yes — ensuring job ${JOB_NAME} is resumed"
    gcloud scheduler jobs resume "${JOB_NAME}" \
        --project="${PROJECT_ID}" --location="${REGION}" >/dev/null 2>&1 || true
fi

cat <<EOF

✓ Done.

Backend env vars to set on the Cloud Run service (already wired in
backend/cloudbuild.yaml — confirm values match this script):

  CAG_SCHEDULER_SA_EMAIL=${SCHEDULER_SA_EMAIL}
  CAG_SCHEDULER_AUDIENCE=${AUDIENCE}

Trigger a manual run to validate the full path:

  gcloud scheduler jobs run ${JOB_NAME} \\
      --project=${PROJECT_ID} --location=${REGION}

Then check Cloud Run logs for ${SERVICE_NAME} — you should see a 200 on
POST /api/cag/export/push/scheduled.
EOF
