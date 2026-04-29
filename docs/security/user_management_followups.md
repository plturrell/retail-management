# User management — follow-up work

This document tracks the three items from the commercial-standards review that
we explicitly did NOT code in the April 2026 hardening pass, and why, plus the
concrete path to close each gap when the business is ready.

Contextual links (in this repo):

- Backend router: `backend/app/routers/users.py`
- Password policy: `backend/app/security/password_policy.py`
- Audit log: `backend/app/audit.py`
- Rate limiter: `backend/app/rate_limit.py`
- Seed script: `tools/scripts/seed_users.py`
- Frontend profile: `apps/staff-portal/src/pages/ProfilePage.tsx`
- Frontend admin: `apps/staff-portal/src/pages/AdminUsersPage.tsx`
- Forced reset page: `apps/staff-portal/src/pages/ForceChangePasswordPage.tsx`

---

## P1 #6 — Multi-factor authentication (MFA / 2FA)

**Why deferred:** Firebase Auth's phone-factor MFA requires:
- reCAPTCHA Enterprise set up on the GCP project (paid, US$1/1000 verifications
  above the free tier).
- A billable SMS provider for phone verification (twilio-backed via Firebase).
- Updating the staff-portal LoginPage to handle the two-factor challenge
  response cycle (`getMultiFactorResolver`, `PhoneAuthProvider.credential`,
  `PhoneMultiFactorGenerator.assertion`).
- An enrollment flow on ProfilePage so users can add/remove factors.
- A policy decision: mandatory for owners? opt-in for staff? grace period?

**Owner-only MFA is the highest-leverage first step** — the two owner accounts
(Craig, Irina) are the most dangerous to compromise.

**When to do it:** Before the business starts processing customer payment data
at scale, or before the first external security review. Not a launch blocker
for a 4-person retail team with owners on 2 devices each.

**Runbook to implement:**
1. Enable reCAPTCHA Enterprise and SMS billing on the GCP project.
2. Add `multiFactor.getSession()` + `PhoneMultiFactorGenerator.assertion` to
   `apps/staff-portal/src/pages/ProfilePage.tsx` behind a feature flag.
3. On the backend, add an endpoint that reports MFA enrollment state for the
   admin user list (it's already on the Firebase user record).
4. When ready, set a policy custom claim (e.g. `mfa_required_for_role: "owner"`)
   and refuse the JWT in `app/auth/firebase.py` if the role matches but no
   second factor was used to mint the token.

**Estimated effort:** 1 focused day plus the GCP billing/reCAPTCHA setup.

---

## P1 #8 — Password history (reuse prevention)

**Why deferred (partial — cannot fully solve):** Firebase Auth does NOT expose
previous password hashes via the Admin SDK, so we literally cannot ask "has
this user used this password before?" against Firebase.

Any password-history implementation therefore requires maintaining a SECOND
store of hashed passwords alongside Firebase — which is both additional
attack surface (we now have hashes to defend) and a maintenance burden
(every password change has to write two places atomically).

**Pragmatic mitigations already in place:**
- HIBP breach check in `app/security/password_policy.py` prevents the #1
  class of reuse-across-sites attacks (users reusing their Netflix password).
- Minimum length 10 + breach check is NIST 800-63B–compliant.
- Rate limit on `/me/change-password` (5/hour) curbs rapid cycling attempts.

**When to do it:** If a SOC 2 / PCI audit explicitly asks for a password-history
control, or if behavioral analysis shows staff flipping between two passwords.

**Runbook to implement (if really needed):**
1. Add a Firestore subcollection `users/{id}/password_history/{ts}` holding
   `{algo: "argon2id", hash: "...", created_at: ...}`. Cap to last 5.
2. In `/me/change-password`, hash the new password with Argon2id (install
   `argon2-cffi`) and compare against all stored hashes BEFORE calling
   `firebase_auth.update_user`. Reject with HTTP 400 on match.
3. On success, prepend the new hash and trim to N.
4. Apply Firestore security rules to make the subcollection server-readable
   only (the user's own client should never see it).

**Estimated effort:** Half a day + ongoing hash-storage risk.

---

## P1 #10 — Email notification on password change

**Why deferred:** Requires a transactional email service (SendGrid / Postmark /
Amazon SES) — we don't yet have one configured for the project. Firebase Auth
sends its own emails for password RESET links (which we already use) but does
NOT send a "your password was changed" notification after a self-service
change.

**When to do it:** Before onboarding the first user outside the core 4-person
ops team — once you have ≥10 accounts, the probability of a phishing-induced
change that the user doesn't notice becomes meaningful.

**Runbook to implement:**
1. Pick a provider. SendGrid has a solid free tier (100 emails/day) that is
   ample for this use case.
2. Store the API key in GCP Secret Manager, expose via `Settings` in
   `app/config.py`.
3. Add `app/email.py` with a single `send_template(to, template, data)` helper.
4. Call it from the end of `change_my_password` and `admin_reset_password` in
   `app/routers/users.py` — AFTER the audit log write, so a delivery failure
   never rolls back the password change.
5. Templates needed:
   - "Your password was changed" (self-change, sent to the user)
   - "Your account password was reset by <admin>" (admin-reset, sent to the
     target; gives them a heads-up in case the admin action was unauthorized)

**Estimated effort:** Half a day including template copy.

---

## Accepted residual risks (launch-day)

Given the 4-person retail ops team and single-store pilot scope:

- **Lost-credentials attack**: we mitigate with HIBP breach check, 5/hr rate
  limit, refresh-token revocation on reset, session-kick on admin disable.
  Without MFA, a phished password is still exploitable for up to an hour from
  the attacker's device. Acceptable for pilot, not for scale.
- **No email notification**: a silent password change by a phished owner is
  undetectable except via the audit log. Owners should scan
  `audit_events` in Firestore weekly during the pilot.
- **No password history**: users can alternate between two passwords. The
  HIBP check is our safety net against the common-case risk.
