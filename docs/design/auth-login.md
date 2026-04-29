# Auth Login Parity

Shared rules for the VictoriaEnso login experience across web, macOS, iOS, and Android.

## Brand

- Show the VictoriaEnso logo once. Do not repeat `VictoriaEnso` as a text heading when the logo already contains the wordmark.
- Use `Retail Management` as the product label beneath the logo.
- Use the platform system font only.
- Keep the login canvas light, quiet, and centered.
- Keep primary controls near 52px tall with soft 17px corners where the platform allows it.
- Use `#0A63F6` as the primary sign-in action colour.

## Behaviour

- Username input maps to `@victoriaenso.com` when the user omits an email domain.
- Password reset is available before sign-in and uses the same generic success message on every platform.
- Failed password sign-ins call `/api/auth/report-failed-login`.
- Successful sign-ins call `/api/auth/report-successful-login`.
- Lockout warnings use the same user-facing messages across platforms.

## Deferred

- Web passkeys use WebAuthn today.
- Native iOS/macOS and Android passkey parity should be a separate platform project because it needs native credential-manager APIs, not a visual login tweak.
