/**
 * Shared helpers for Playwright E2E specs.
 *
 * The big one here is `enableVirtualAuthenticator`: it attaches a
 * Chrome-DevTools-backed "virtual authenticator" to a page so WebAuthn
 * ceremonies (register / authenticate) auto-resolve without touching the
 * Mac's Touch ID sensor. This is the only way to script passkey flows in
 * CI without real hardware.
 *
 * Docs: https://chromedevtools.github.io/devtools-protocol/tot/WebAuthn/
 */
import type { CDPSession, Page } from "@playwright/test";
import { expect } from "@playwright/test";

export interface TestCreds {
  email: string;
  password: string;
}

export function getTestCreds(): TestCreds {
  const email = process.env.TEST_EMAIL;
  const password = process.env.TEST_PASSWORD;
  if (!email || !password) {
    throw new Error(
      "E2E tests require TEST_EMAIL and TEST_PASSWORD env vars. " +
      "Use an existing Firebase user (e.g. one from tools/scripts/seed_users.py).",
    );
  }
  return { email, password };
}

export interface VirtualAuthenticator {
  cdp: CDPSession;
  authenticatorId: string;
}

/**
 * Install a virtual authenticator into the page. Returns a handle we can
 * later use to inspect registered credentials or clean up.
 *
 * - `protocol: "ctap2"` + `transport: "internal"` makes it look like a
 *   platform authenticator (Touch ID / Windows Hello), so our RP's UV-required
 *   policy is satisfied.
 * - `hasResidentKey` + `hasUserVerification` + `isUserVerified` together say
 *   "the user just touched the sensor successfully" — no prompt appears.
 * - `automaticPresenceSimulation` auto-clicks through the ceremony.
 */
export async function enableVirtualAuthenticator(page: Page): Promise<VirtualAuthenticator> {
  const cdp = await page.context().newCDPSession(page);
  await cdp.send("WebAuthn.enable", { enableUI: false });
  const { authenticatorId } = await cdp.send("WebAuthn.addVirtualAuthenticator", {
    options: {
      protocol: "ctap2",
      transport: "internal",
      hasResidentKey: true,
      hasUserVerification: true,
      isUserVerified: true,
      automaticPresenceSimulation: true,
    },
  });
  return { cdp, authenticatorId };
}

export async function removeVirtualAuthenticator(va: VirtualAuthenticator): Promise<void> {
  try {
    await va.cdp.send("WebAuthn.removeVirtualAuthenticator", {
      authenticatorId: va.authenticatorId,
    });
  } catch {
    /* already gone */
  }
}

/**
 * Sign in with username + password via the login form. Waits until the /schedule
 * page is reachable as the success signal.
 */
export async function loginWithPassword(page: Page, creds: TestCreds): Promise<void> {
  await page.goto("/login", { waitUntil: "domcontentloaded" });
  await page.getByPlaceholder("Username").fill(creds.email.split("@")[0]);
  await page.getByPlaceholder("Password").fill(creds.password);
  await page.getByRole("button", { name: /^sign in$/i }).click();
  // AppShell is only reachable after auth resolves.
  await expect(page).toHaveURL(/\/(schedule|force-change-password)/, { timeout: 15_000 });
}

/**
 * Dismiss the force-change-password page if Firebase decides this user needs
 * it. Not a real concern for long-lived test users, but defensive.
 */
export async function skipForceChangePage(page: Page): Promise<void> {
  if (page.url().includes("/force-change-password")) {
    throw new Error(
      "Test user is flagged must_change_password — clear the claim before running E2E.",
    );
  }
}

export async function signOut(page: Page): Promise<void> {
  // The shell exposes a "Sign out" button in the side nav footer.
  const signOut = page.getByRole("button", { name: /sign out|log out/i });
  if (await signOut.count()) {
    await signOut.first().click();
  } else {
    // Fallback: call Firebase signOut via the page context.
    await page.evaluate(async () => {
      const { getAuth, signOut: fbSignOut } = await import("firebase/auth");
      await fbSignOut(getAuth());
    });
    await page.goto("/login");
  }
  await expect(page).toHaveURL(/\/login/, { timeout: 10_000 });
}
