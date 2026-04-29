#!/usr/bin/env bash
set -euo pipefail

# Clean generated build outputs and tool caches that are safe to recreate.
# Usage:
#   tools/scripts/clean_local_caches.sh
#   CACHE_ROOT=/Volumes/ExternalCache tools/scripts/clean_local_caches.sh --setup-env
#   tools/scripts/clean_local_caches.sh --dry-run

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CACHE_ROOT="${CACHE_ROOT:-/Volumes/ExternalCache/retailmanagement}"
DRY_RUN=0
SETUP_ENV=0

for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY_RUN=1 ;;
        --setup-env) SETUP_ENV=1 ;;
        -h|--help)
            sed -n '2,18p' "$0"
            exit 0
            ;;
        *)
            echo "Unknown argument: $arg" >&2
            exit 2
            ;;
    esac
done

run() {
    if [[ "$DRY_RUN" == "1" ]]; then
        printf 'DRY RUN: %q' "$1"
        shift
        for arg in "$@"; do printf ' %q' "$arg"; done
        printf '\n'
        return
    fi
    "$@"
}

size_of() {
    du -sh "$@" 2>/dev/null || true
}

echo "Local disk before cleanup:"
df -h / /System/Volumes/Data | tail -n +1
echo ""

if [[ "$SETUP_ENV" == "1" ]]; then
    echo "Preparing external cache root: $CACHE_ROOT"
    run mkdir -p \
        "$CACHE_ROOT/npm" \
        "$CACHE_ROOT/pip" \
        "$CACHE_ROOT/gradle" \
        "$CACHE_ROOT/homebrew" \
        "$CACHE_ROOT/firebase-emulators" \
        "$CACHE_ROOT/xdg" \
        "$CACHE_ROOT/XcodeDerivedData"
fi

paths=(
    "$REPO_ROOT/apps/android/app/build"
    "$REPO_ROOT/apps/android/build"
    "$REPO_ROOT/apps/android/.gradle"
    "$REPO_ROOT/apps/staff-portal/dist"
    "$REPO_ROOT/backend/.pytest_cache"
    "$REPO_ROOT/data/ocr_outputs"
    "$REPO_ROOT/data/mangle_facts"
    "$REPO_ROOT/data/uploads/invoices"
    "$REPO_ROOT/mangle_facts"
    "$REPO_ROOT/mangle_facts_test"
    "$REPO_ROOT/ocr_outputs"
    "$HOME/Library/Developer/Xcode/DerivedData/retailmanagement-"*
    "$HOME/Library/Caches/org.swift.swiftpm"
    "$HOME/.npm/_cacache"
    "$HOME/Library/Caches/Homebrew"
    "$HOME/Library/Caches/pip"
)

echo "Cleaning generated outputs and recreatable caches..."
for path in "${paths[@]}"; do
    if compgen -G "$path" >/dev/null; then
        for match in $path; do
            [[ -e "$match" ]] || continue
            echo "  removing $match ($(size_of "$match" | awk '{print $1}'))"
            run rm -rf "$match"
        done
    fi
done

echo ""
echo "Local disk after cleanup:"
df -h / /System/Volumes/Data | tail -n +1

cat <<EOF

External cache env for this shell:
  export CACHE_ROOT="$CACHE_ROOT"
  export npm_config_cache="$CACHE_ROOT/npm"
  export PIP_CACHE_DIR="$CACHE_ROOT/pip"
  export GRADLE_USER_HOME="$CACHE_ROOT/gradle"
  export HOMEBREW_CACHE="$CACHE_ROOT/homebrew"
  export FIREBASE_EMULATOR_DOWNLOAD_DIR="$CACHE_ROOT/firebase-emulators"
  export XDG_CACHE_HOME="$CACHE_ROOT/xdg"

iOS builds:
  xcodebuild -derivedDataPath "$CACHE_ROOT/XcodeDerivedData" ...
EOF
