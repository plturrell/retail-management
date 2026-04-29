# CAG / NEC Jewel POS — Tenant Onboarding Runbook

End-to-end procedure for connecting Victoria Enso's retail-management
system to the Changi Airport Group / NEC Asia Pacific D365FO POS
("Jewel POS"). Read this alongside the source guides in
`docs/CAG - NEC Retail POS Onboarding Guides/` (PDFs) and the spec
`CAG-Jewel-ISD-Interfaces TXT Formats v1.7.6j.pdf`.

---

## 0. One-time setup checklist

| Item | Provided by | Stored in |
| --- | --- | --- |
| 6/7-digit Customer No. (`<tenant>`) | CAG | `.env` `CAG_SFTP_TENANT_FOLDER`; per-store `nec_tenant_code` |
| 5-digit Store ID (`<storeID>`) | NEC | per-store `nec_store_id` |
| SFTP host / port / user | NEC | `.env` `CAG_SFTP_HOST` / `_PORT` / `_USER` |
| SFTP password **or** key | NEC | `.env` `CAG_SFTP_PASSWORD` or `_KEY_PATH` (preferred) |
| Tenant Workspace login (D365FO) | CAG | 1Password |
| MFA TOTP seed | CAG (during enrolment) | Authenticator app |
| Hardware list per store | Tenant procurement | `docs/CAG - NEC Retail POS Onboarding Guides/POS Hardware/` |

Until CAG provides the Customer No. and Store IDs the SFTP push will
fail at config validation; the TXT bundle endpoint still works for
local testing using placeholder IDs.

---

## 1. MFA & Tenant Workspace access

Source: `POS Backend (BE) Guide/[Latest] CAG NEC - Managing your MFA Account.pdf` and `MFA D365 BE App Notification Setup.pdf`.

1. CAG sends an enrolment email to the registered tenant admin.
2. Install Microsoft Authenticator on a phone dedicated to retail ops.
3. Scan the QR code from the enrolment portal — the token will be needed
   at every D365FO login.
4. Store backup codes in 1Password under `CAG NEC MFA Backup`.
5. Test by logging into the Tenant Workspace and confirming the
   "Discount headers" page is visible (we need this for PROMO uploads).

---

## 2. Discount-header pre-requisite

Source: spec section 4.6.

The PROMO TXT file references discount IDs that must already exist in
D365FO as Discount Headers. Create these once via Tenant Workspace
before the first PROMO upload:

| DISC_ID | Name | Type | Value |
| --- | --- | --- | --- |
| `VE_GENERAL_10` | 10% General | PercentOff | 10 |
| `VE_SPECIAL_15` | 15% Special | PercentOff | 15 |
| `VE_DIRECTOR_20` | 20% Director Approved | PercentOff | 20 |
| `VE_CLEARANCE_25` | 25% Clearance Special | PercentOff | 25 |
| `VE_STAFFCARD_20` | 20% Jewel Staff Card | PercentOff | 20 |
| `VE_VIP_LOYALTY_20` | 20% VIP Loyalty Customer | PercentOff | 20 |

These IDs are mirrored in `app.services.nec_jewel_export.PROMO_TIERS`.

---

## 3. SFTP credentials & connectivity test

Source: `Import and Export Sales Interface/[Latest] CAG NEC - SFTP guide v1.1.pdf`.

1. Drop the host, port, username, and either the private key or password
   into `backend/.env`:

   ```env
   CAG_SFTP_HOST=sftp.cag.example
   CAG_SFTP_PORT=22
   CAG_SFTP_USER=<assigned-user>
   CAG_SFTP_KEY_PATH=~/.ssh/cag_nec_id_rsa
   CAG_SFTP_TENANT_FOLDER=200151
   ```

2. Smoke-test the connection from the tenant network (CAG SFTP is often
   IP-allow-listed):

   ```bash
   sftp -P 22 <user>@<host>
   sftp> ls 200151/Inbound
   # Expect: Working  Process  Archive  Error
   ```

3. Validate from our backend without uploading:

   ```bash
   python tools/scripts/push_nec_master_files.py \
       --tenant 200151 \
       --nec-store-id 80001 \
       --dry-run
   ```

   This builds the six TXT files into
   `data/exports/cag_nec_200151_<ts>/` so we can hand-inspect before any
   real upload.

---

## 4. First-batch upload (no size limit)

Source: SFTP guide v1.1 page 2 — first batch is unlimited; subsequent
uploads are capped at 2 MB / ~15 000 lines.

1. Confirm sale-readiness in the staff portal Data Quality page; the
   gate (`sale_ready`, status, has price, has PLU, has description) is
   already enforced by `fetch_sellable_skus_from_firestore`.
2. Run the push script without `--dry-run`:

   ```bash
   python tools/scripts/push_nec_master_files.py \
       --tenant 200151 --nec-store-id 80001
   ```

3. Within ~3 hours (NEC's import scheduler runs every 3 h from 08:00
   SGT), files move from `Inbound/Working/` to `Inbound/Archive/`
   (success) or `Inbound/Error/` (failure).
4. Pull error logs:

   ```bash
   curl -H "Authorization: Bearer $TOKEN" \
       https://api.victoriaenso.app/api/cag/export/errors
   ```

---

## 5. Delta uploads

After the first batch, only push **incremental/delta** records to keep
each TXT under 2 MB. The current bundle builder always emits a full
snapshot — use `MODE=A` (add/update) so D365FO upserts. To switch to
delete-then-add semantics for clearance flows, pass `MODE=D` rows on a
separate run; this is currently a manual override on the CLI level
(see follow-up plan for delta diffing).

The retail backend allows the same SKU to have overlapping price rows;
the cheapest active price wins (spec section 4.4 NOTE).

---

## 6. Error-log triage

Source: SFTP guide v1.1 — `*.errorLog` lines look like:

```
Failed: Line 3 - Mandatory fields are not filled: SKU_CODE
Accepted: Line 10 - SKU_DESC is truncated, exceeded maximum 60 Characters
```

| Error message | Root cause | Fix in our system |
| --- | --- | --- |
| `CHILD_CATG_CODE not found` | CATG file missing a parent before its child | Ensure CATG file is uploaded first; check `make_tenant_catg_tree` ordering |
| `Unable to import SKU as CATG is not provided` | CATG hasn't been ingested yet | Re-upload CATG and wait for next 3-hour scheduler tick |
| `Unable to import PLU as SKU is not provided` | SKU file rejected before PLU | Resolve SKU errors first; rerun |
| `PLU code duplicated` | Two products share a PLU | `tools/scripts/repair_invalid_plus_codes.py` then re-export |
| `SKU_DESC is truncated` | Description >60 chars | Cosmetic only (Accepted); shorten in master data when convenient |
| `Mandatory fields are not filled` | Missing brand / age-group / TAX_CODE / etc. | Use `/api/data-quality` to surface; backfill in Firestore |

Errors are streamed back through `GET /api/cag/export/errors`. The
parser is `app.services.cag_sftp.parse_error_log` and is unit-tested.

---

## 7. Hardware procurement

Source: `POS Hardware/[Latest] CAG NEC - POS Hardware For GM Tenants.xlsx`.

CAG mandates specific peripherals (printer, MSR, scanner, EFTPOS pinpad,
cash drawer, customer-display) per concession. These are **not** in
scope for our backend; track procurement in the Notion Hardware DB and
attach the CAG-approved list when ordering.

---

## 8. Frontend cashier training

Source: `POS Frontend (FE) Guide/[Latest] CAG NEC - GM POS User Guide v1.15f.pdf` and `Enhanced UI For ChangiPay v2.pdf`.

The cashier-facing app is the NEC-supplied D365FO Modern POS — we don't
build or theme it. Training is delivered by NEC. Tenant tasks:

- Schedule POS users in D365FO Tenant Workspace before opening day.
- Walk new staff through the GM POS user guide (PDF chapters 1-7).
- Familiarise managers with X / Z reading, sign-on/off, no-sale, and the
  ChangiPay flow.

---

## 9. Operational cadence

| Cadence | Action | Owner |
| --- | --- | --- |
| Daily 07:30 SGT | `push_nec_master_files.py` cron (delta) | Ops |
| Daily 08:00 SGT | NEC import window starts | NEC scheduler |
| Daily 09:30 SGT | Pull error logs, triage in DataQualityPage | Ops |
| Weekly Mon | Reconcile `Inbound/Archive/` filenames against bundle audit copies | Ops |
| Monthly | Review `data/exports/cag_nec_<tenant>_*` retention; archive >90 d | DevOps |

---

## 10. Out of scope for this plan

The following are tracked in a follow-up integration plan and are
**not** wired up by this runbook:

- Outbound `SALES_*.txt` (EOD) and `EJ_*.txt` parsing — currently the
  placeholder XML parser in `backend/app/routers/nec_import.py` is
  retained as a stub.
- Changi Rewards loyalty linking (CMD 161).
- ChangiPay payment-line reconciliation.
- Customer-order / deposit / sales-order flows (CMD 104, 115).
- Currency exchange rate ingestion (XML interface).
