# Local Cache and Object Storage

Use GCP Cloud Storage for durable OCR/AI artifacts and keep local build caches disposable.

## External Cache Root

If an external volume is available, prepare it once:

```bash
CACHE_ROOT=/Volumes/ExternalCache/retailmanagement tools/scripts/clean_local_caches.sh --setup-env
```

Add this to your shell profile:

```bash
export CACHE_ROOT=/Volumes/ExternalCache/retailmanagement
export npm_config_cache="$CACHE_ROOT/npm"
export PIP_CACHE_DIR="$CACHE_ROOT/pip"
export GRADLE_USER_HOME="$CACHE_ROOT/gradle"
export HOMEBREW_CACHE="$CACHE_ROOT/homebrew"
export FIREBASE_EMULATOR_DOWNLOAD_DIR="$CACHE_ROOT/firebase-emulators"
export XDG_CACHE_HOME="$CACHE_ROOT/xdg"
```

## Cleanup

Preview cleanup:

```bash
tools/scripts/clean_local_caches.sh --dry-run
```

Run cleanup:

```bash
tools/scripts/clean_local_caches.sh
```

This removes generated app builds, pytest cache, SwiftPM cache, npm/Homebrew/pip caches, and generated OCR/Mangle folders. It does not remove source files.

## Build Commands

Web:

```bash
cd apps/staff-portal
npm run build
```

Android:

```bash
export JAVA_HOME="/Users/victoriaenso/.homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home"
export ANDROID_HOME="/Users/victoriaenso/.homebrew/share/android-commandlinetools"
export ANDROID_SDK_ROOT="$ANDROID_HOME"
export GRADLE_USER_HOME="${CACHE_ROOT:-/Volumes/ExternalCache/retailmanagement}/gradle"
cd apps/android
./gradlew :app:assembleDebug --no-daemon
```

iOS:

```bash
xcodebuild \
  -derivedDataPath "${CACHE_ROOT:-/Volumes/ExternalCache/retailmanagement}/XcodeDerivedData" \
  -project apps/ios/retailmanagement.xcodeproj \
  -scheme retailmanagement \
  -sdk iphonesimulator \
  -configuration Debug build \
  CODE_SIGNING_ALLOWED=NO
```

Firebase emulator:

```bash
export JAVA_HOME="/Users/victoriaenso/.homebrew/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home"
export FIREBASE_EMULATOR_DOWNLOAD_DIR="${CACHE_ROOT:-/Volumes/ExternalCache/retailmanagement}/firebase-emulators"
firebase emulators:start --only firestore --project victoriaensoapp
```

## GCP Object Storage

Durable OCR/AI artifacts belong in:

```text
gs://victoriaensoapp-ai-artifacts
```

Backend config:

```bash
GCP_PROJECT_ID=victoriaensoapp
AI_GCS_BUCKET=victoriaensoapp-ai-artifacts
```

The backend GCS helper is `backend/app/services/gcs.py`. New large AI inputs should use `POST /api/ai/jobs/upload` first, then dispatch jobs with the returned `gcs_input_uri`.
