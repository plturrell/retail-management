import { expect, test } from "@playwright/test";

const protectedAuthUrls = [
  /\/api\/auth\/report-failed-login$/,
  /\/api\/auth\/report-successful-login$/,
  /\/api\/webauthn\/login\/start$/,
  /\/api\/webauthn\/login\/finish$/,
  /identitytoolkit\/v\d+\/accounts:signInWithPassword/,
  /identitytoolkit\/v\d+\/accounts:sendOobCode/,
];

async function guardAuthTraffic(page: import("@playwright/test").Page) {
  const hits: string[] = [];

  await page.route("**/*", async (route) => {
    const url = route.request().url();
    if (protectedAuthUrls.some((pattern) => pattern.test(url))) {
      hits.push(url);
      await route.abort();
      return;
    }
    await route.continue();
  });

  return hits;
}

test.describe("Login UI safety checks", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/login?e2e-ui=1", { waitUntil: "domcontentloaded" });
  });

  test("renders the aligned login shell without duplicate brand text", async ({ page }) => {
    await expect(page.getByAltText("VictoriaEnso")).toBeVisible();
    await expect(page.getByText("VictoriaEnso", { exact: true })).toHaveCount(0);
    await expect(page.getByText("Retail Management")).toBeVisible();

    await expect(page.getByPlaceholder("Username")).toBeVisible();
    await expect(page.getByPlaceholder("Password")).toBeVisible();
    await expect(page.getByRole("button", { name: "Sign In", exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: /face id|fingerprint/i })).toBeVisible();
    await expect(page.getByRole("button", { name: "Forgot password?" })).toBeVisible();
  });

  test("keeps Craig blank-password check client-side", async ({ page }) => {
    const authTraffic = await guardAuthTraffic(page);
    const username = page.getByPlaceholder("Username");
    const password = page.getByPlaceholder("Password");

    await username.fill("craig");
    await page.getByRole("button", { name: "Sign In", exact: true }).click();

    await expect(username).toHaveValue("craig");
    await expect(password).toHaveValue("");
    await expect(password).toBeFocused();
    await expect(page).toHaveURL(/\/login/);
    await expect(password).toHaveJSProperty("validity.valueMissing", true);
    expect(authTraffic).toEqual([]);
  });

  test("blocks reset and biometric flows until a username is entered", async ({ page }) => {
    const authTraffic = await guardAuthTraffic(page);

    await page.getByRole("button", { name: "Forgot password?" }).click();
    await expect(page.getByText("Enter your username above first, then tap “Forgot password”."))
      .toBeVisible();

    await page.getByRole("button", { name: /face id|fingerprint/i }).click();
    await expect(page.getByText("Enter your username above first, then tap the biometric button."))
      .toBeVisible();
    expect(authTraffic).toEqual([]);
  });
});
