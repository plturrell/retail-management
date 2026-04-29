#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${PROJECT_ID:-victoriaensoapp}"
PROJECT_NUMBER="${PROJECT_NUMBER:-568773738080}"
WEB_DISPLAY_NAME="${WEB_DISPLAY_NAME:-VictoriaEnso Staff Portal}"
ANDROID_DISPLAY_NAME="${ANDROID_DISPLAY_NAME:-VictoriaEnso Android}"
IOS_DISPLAY_NAME="${IOS_DISPLAY_NAME:-VictoriaEnso iOS}"
ANDROID_PACKAGE_NAME="${ANDROID_PACKAGE_NAME:-com.retailmanagement}"
IOS_BUNDLE_ID="${IOS_BUNDLE_ID:-com.victoriaenso.retailmanagement}"
WEB_ENV_FILE="${WEB_ENV_FILE:-apps/staff-portal/.env}"
ANDROID_CONFIG_FILE="${ANDROID_CONFIG_FILE:-apps/android/app/google-services.json}"
IOS_CONFIG_FILE="${IOS_CONFIG_FILE:-apps/ios/retailmanagement/GoogleService-Info.plist}"

require_tool() {
    if ! command -v "$1" >/dev/null 2>&1; then
        echo "Missing required tool: $1" >&2
        exit 1
    fi
}

require_tool firebase
require_tool jq

firebase_json() {
    firebase --project "$PROJECT_ID" --json "$@"
}

app_id_for_display_name() {
    local platform="$1"
    local display_name="$2"
    firebase_json apps:list "$platform" \
        | jq -r --arg display_name "$display_name" '
            (.result // [])
            | map(select(.displayName == $display_name))
            | first
            | .appId // empty
        '
}

ensure_app() {
    local platform="$1"
    local display_name="$2"
    shift 2

    local app_id
    app_id="$(app_id_for_display_name "$platform" "$display_name")"
    if [[ -n "$app_id" ]]; then
        echo "$app_id"
        return
    fi

    firebase_json apps:create "$platform" "$display_name" "$@" \
        | jq -r '.result.appId // .result.app_id // empty'
}

echo "Syncing Firebase apps for ${PROJECT_ID}..."

WEB_APP_ID="$(ensure_app WEB "$WEB_DISPLAY_NAME")"
ANDROID_APP_ID="$(ensure_app ANDROID "$ANDROID_DISPLAY_NAME" --package-name "$ANDROID_PACKAGE_NAME")"
IOS_APP_ID="$(ensure_app IOS "$IOS_DISPLAY_NAME" --bundle-id "$IOS_BUNDLE_ID")"

if [[ -z "$WEB_APP_ID" || -z "$ANDROID_APP_ID" || -z "$IOS_APP_ID" ]]; then
    echo "Failed to resolve all Firebase app IDs." >&2
    exit 1
fi

mkdir -p "$(dirname "$WEB_ENV_FILE")" "$(dirname "$ANDROID_CONFIG_FILE")" "$(dirname "$IOS_CONFIG_FILE")"

WEB_CONFIG_JSON="$(firebase_json apps:sdkconfig WEB "$WEB_APP_ID" | jq -r '.result.sdkConfig // .result')"
API_KEY="$(jq -r '.apiKey // empty' <<<"$WEB_CONFIG_JSON")"
AUTH_DOMAIN="$(jq -r '.authDomain // empty' <<<"$WEB_CONFIG_JSON")"
STORAGE_BUCKET="$(jq -r '.storageBucket // empty' <<<"$WEB_CONFIG_JSON")"
MESSAGING_SENDER_ID="$(jq -r '.messagingSenderId // empty' <<<"$WEB_CONFIG_JSON")"
APP_ID="$(jq -r '.appId // empty' <<<"$WEB_CONFIG_JSON")"

if [[ -z "$API_KEY" || -z "$APP_ID" ]]; then
    echo "Firebase web SDK config is missing apiKey/appId." >&2
    exit 1
fi

{
    printf 'VITE_API_URL=https://retailsg-api-%s.asia-southeast1.run.app/api\n' "$PROJECT_NUMBER"
    printf 'VITE_FIREBASE_API_KEY=%s\n' "$API_KEY"
    printf 'VITE_FIREBASE_AUTH_DOMAIN=%s\n' "${AUTH_DOMAIN:-${PROJECT_ID}.firebaseapp.com}"
    printf 'VITE_FIREBASE_PROJECT_ID=%s\n' "$PROJECT_ID"
    printf 'VITE_FIREBASE_STORAGE_BUCKET=%s\n' "${STORAGE_BUCKET:-${PROJECT_ID}.firebasestorage.app}"
    printf 'VITE_FIREBASE_MESSAGING_SENDER_ID=%s\n' "${MESSAGING_SENDER_ID:-$PROJECT_NUMBER}"
    printf 'VITE_FIREBASE_APP_ID=%s\n' "$APP_ID"
} > "$WEB_ENV_FILE"

firebase --project "$PROJECT_ID" apps:sdkconfig ANDROID "$ANDROID_APP_ID" --out "$ANDROID_CONFIG_FILE" >/dev/null
firebase --project "$PROJECT_ID" apps:sdkconfig IOS "$IOS_APP_ID" --out "$IOS_CONFIG_FILE" >/dev/null

echo "Firebase app configs synced:"
echo "  Web:     $WEB_ENV_FILE"
echo "  Android: $ANDROID_CONFIG_FILE"
echo "  iOS:     $IOS_CONFIG_FILE"
