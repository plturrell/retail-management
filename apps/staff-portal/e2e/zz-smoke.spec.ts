/**
 * API-level smoke tests — no browser required for most of these.
 *
 * Covers the unauthenticated surface area added in the hardening pass:
 *   - /webauthn/login/start (pre-auth)
 *   - /auth/report-failed-login rate limiter
 *   - /auth/report-successful-login rate limiter
 *
 * These catch regressions in the slowapi wiring (which already bit us
 * once — the @limiter decorator needs `response: Response` in the signature
 * or the first hit returns 500).
 */
import { expect, test } from "@playwright/test";

const API_BASE = process.env.E2E_API_URL || "http://localhost:8000";

test.describe("API smoke", () => {
  test("/webauthn/login/start succeeds and shape is correct", async ({ request }) => {
    const res = await request.post(`${API_BASE}/api/webauthn/login/start`, {
      headers: { "Content-Type": "application/json", Origin: "http://localhost:5173" },
      data: { email: `smoke-${Date.now()}@example.com` },
    });
    expect(res.ok()).toBeTruthy();
    const body = await res.json();
    expect(body).toHaveProperty("challenge_id");
    expect(body).toHaveProperty("options");
    expect(body.options.userVerification).toBe("required");
  });

  test("/auth/report-failed-login returns counter info without 500", async ({ request }) => {
    // Uses a unique email so we don't bump the counter for a real user.
    const res = await request.post(`${API_BASE}/api/auth/report-failed-login`, {
      headers: { "Content-Type": "application/json" },
      data: { email: `smoke-failed-${Date.now()}@example.com` },
    });
    expect(res.ok()).toBeTruthy();
    const body = await res.json();
    expect(body).toHaveProperty("locked");
    expect(body).toHaveProperty("remaining");
    expect(body).toHaveProperty("threshold");
  });

  test("/auth/report-successful-login always returns ok", async ({ request }) => {
    const res = await request.post(`${API_BASE}/api/auth/report-successful-login`, {
      headers: { "Content-Type": "application/json" },
      data: { email: `smoke-success-${Date.now()}@example.com` },
    });
    expect(res.ok()).toBeTruthy();
    expect(await res.json()).toEqual({ ok: true });
  });

  test("rate limiter kicks in on /webauthn/login/start at 20/min", async ({ request }) => {
    test.slow();
    const email = `ratelimit-${Date.now()}@example.com`;
    let sawTooMany = false;
    for (let i = 0; i < 25; i++) {
      const res = await request.post(`${API_BASE}/api/webauthn/login/start`, {
        headers: { "Content-Type": "application/json", Origin: "http://localhost:5173" },
        data: { email },
      });
      if (res.status() === 429) {
        sawTooMany = true;
        break;
      }
    }
    expect(sawTooMany).toBe(true);
  });
});
