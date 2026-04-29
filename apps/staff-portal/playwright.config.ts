import { defineConfig, devices } from "@playwright/test";
import * as fs from "node:fs";
import * as path from "node:path";
import { fileURLToPath } from "node:url";

// ESM-safe __dirname (package.json has "type": "module").
const __dirname = path.dirname(fileURLToPath(import.meta.url));

/**
 * Playwright E2E configuration for the staff portal.
 *
 * Fully automated: Playwright starts the Vite frontend and the uvicorn
 * backend itself (reusing them if already running) and loads the seeded
 * test-user credentials from `.env.e2e`. After the initial seed you can
 * just `npm run test:e2e` with no manual shell juggling.
 *
 * Dev flow:
 *   1. python tools/scripts/seed_e2e_test_user.py --apply    (one-time)
 *   2. npm --prefix apps/staff-portal run test:e2e           (everywhere after)
 *
 * Required env (auto-loaded from .env.e2e if present):
 *   TEST_EMAIL     — Firebase user to sign in with
 *   TEST_PASSWORD  — that user's password
 *
 * Optional env:
 *   E2E_BASE_URL   — frontend base URL (default http://localhost:5173)
 *   E2E_API_URL    — backend base URL  (default http://localhost:8000)
 *   PW_NO_SERVER   — set to "1" to skip auto-starting servers
 */

// ── Auto-load .env.e2e so TEST_EMAIL / TEST_PASSWORD flow through without
//    the caller having to source anything. Small hand-rolled parser avoids
//    pulling dotenv just for this.
const envE2ePath = path.resolve(__dirname, ".env.e2e");
if (fs.existsSync(envE2ePath)) {
  for (const line of fs.readFileSync(envE2ePath, "utf8").split("\n")) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    const eq = trimmed.indexOf("=");
    if (eq < 0) continue;
    const key = trimmed.slice(0, eq);
    const value = trimmed.slice(eq + 1);
    if (!(key in process.env)) process.env[key] = value;
  }
}

const BACKEND_DIR = path.resolve(__dirname, "../../backend");
const BASE_URL = process.env.E2E_BASE_URL || "http://localhost:5173";
const API_URL = process.env.E2E_API_URL || "http://localhost:8000";

// Playwright's webServer supports array form to spawn multiple services.
// `reuseExistingServer: true` means if you already have `npm run dev` /
// uvicorn in another terminal, we don't fight them.
const webServer = process.env.PW_NO_SERVER
  ? undefined
  : [
      {
        command: "npm run dev -- --port 5173",
        url: `${BASE_URL}/`,
        cwd: __dirname,
        reuseExistingServer: true,
        timeout: 60_000,
        stdout: "pipe" as const,
        stderr: "pipe" as const,
      },
      {
        // Relies on `.venv` inside backend/ and service-account creds being
        // available via ADC or GOOGLE_APPLICATION_CREDENTIALS in the parent
        // shell. Inherited env carries those through.
        command: ".venv/bin/uvicorn app.main:app --port 8000",
        url: `${API_URL}/openapi.json`,
        cwd: BACKEND_DIR,
        reuseExistingServer: true,
        timeout: 60_000,
        stdout: "pipe" as const,
        stderr: "pipe" as const,
      },
    ];

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  fullyParallel: false,           // Auth flows share a Firebase user; serialise to avoid self-races.
  retries: process.env.CI ? 1 : 0,
  reporter: [["list"]],
  use: {
    baseURL: BASE_URL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "off",
    headless: true,
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  webServer,
});
