/**
 * E2E: biometric sign-in (WebAuthn / passkeys).
 *
 * Covers the full loop:
 *   1. Password sign-in (baseline)
 *   2. Register a passkey with a virtual authenticator
 *   3. Confirm it appears on the Profile page
 *   4. Sign out
 *   5. Sign back in using the passkey — no password typed
 *   6. Remove the passkey
 *
 * Preconditions:
 *   - Dev servers running (staff-portal on :5173, backend on :8000)
 *   - TEST_EMAIL / TEST_PASSWORD env vars set for a live Firebase user
 *   - User has NO other passkeys registered (or the "remove all" step at
 *     the top of the test will clear them)
 */
import { expect, test } from "@playwright/test";
import {
  enableVirtualAuthenticator,
  getTestCreds,
  loginWithPassword,
  removeVirtualAuthenticator,
  signOut,
  skipForceChangePage,
} from "./helpers";

test.describe("WebAuthn / Passkey flow", () => {
  const creds = getTestCreds();

  test("register, sign in with biometrics, and remove a passkey", async ({ page }) => {
    // ── 1. Password sign-in baseline. ──────────────────────────────────────
    //    We attach the virtual authenticator AFTER the first navigation.
    //    Attaching it on the initial about:blank frame can race with the
    //    first page.goto (frame-detached → ERR_ABORTED) on some Chromium
    //    builds. The authenticator only has to exist before the first
    //    WebAuthn ceremony, not before the first navigation.
    await loginWithPassword(page, creds);
    await skipForceChangePage(page);

    const va = await enableVirtualAuthenticator(page);

    try {

      // ── 2. Clean any pre-existing passkeys so the test is idempotent. ────
      await page.goto("/profile", { waitUntil: "domcontentloaded" });
      await expect(page.getByText(/biometric sign-in/i)).toBeVisible();

      // Single dialog handler that covers BOTH the confirm() used by
      // "Remove" and the prompt() used by "Register this device" — multiple
      // stacked handlers all race to accept the same dialog and crash.
      page.on("dialog", (d) => {
        if (d.type() === "prompt") void d.accept("Playwright virtual device");
        else void d.accept();
      });

      // Clean any pre-existing passkeys (idempotent — lets us rerun).
      while (await page.getByRole("button", { name: /^remove$/i }).count() > 0) {
        await page.getByRole("button", { name: /^remove$/i }).first().click();
        await page.waitForTimeout(400);
      }

      // ── 3. Register a new passkey. ───────────────────────────────────────
      await page.getByRole("button", { name: /register this device/i }).click();

      // Success state: card shows the new device and a success banner.
      await expect(page.getByText("Playwright virtual device")).toBeVisible({ timeout: 15_000 });
      await expect(page.getByText(/registered/i).first()).toBeVisible();

      // ── 4. Sign out. ─────────────────────────────────────────────────────
      await signOut(page);

      // ── 5. Sign in with biometrics. ──────────────────────────────────────
      // The virtual authenticator is scoped to this page; it survives across
      // in-page navigations (SPA) but NOT across page.goto() to an HTTP page
      // in Chromium IF the context is replaced. We're in the same context
      // still, so the authenticator and its resident credential persist.
      await page.goto("/login", { waitUntil: "domcontentloaded" });
      await page.getByPlaceholder("Username").fill(creds.email.split("@")[0]);
      await page.getByRole("button", { name: /face id|fingerprint|biometric/i }).click();

      // Successful biometric login lands on /schedule.
      await expect(page).toHaveURL(/\/schedule/, { timeout: 15_000 });

      // ── 6. Remove the passkey we registered. ─────────────────────────────
      await page.goto("/profile", { waitUntil: "domcontentloaded" });
      await expect(page.getByText("Playwright virtual device")).toBeVisible();
      await page.getByRole("button", { name: /^remove$/i }).first().click();
      // Card should now be empty.
      await expect(page.getByText(/no passkeys registered yet/i)).toBeVisible({ timeout: 5_000 });
    } finally {
      await removeVirtualAuthenticator(va);
    }
  });

  test("register/start requires authentication", async ({ request }) => {
    const apiBase = process.env.E2E_API_URL || "http://localhost:8000";
    const res = await request.post(`${apiBase}/api/webauthn/register/start`, {
      headers: { "Content-Type": "application/json" },
      data: {},
    });
    expect(res.status()).toBe(401);
  });
});
