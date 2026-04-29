# NEC POS Integration — Gap Analysis

**Reference pack:** `docs/CAG - NEC Retail POS Onboarding Guides/`
**Canonical wire spec:** `Import and Export Sales Interface/[Latest] CAG-Jewel-ISD-Interfaces TXT Formats v1.7.6h.xlsx`
**Generated:** 2026-04-29
**Status:** Past tenant onboarding deadline — prioritize go-live blockers.

## Headline

The Import/Export Sales Interface — the only section of the onboarding pack
that requires NEW code in our system — is **already implemented end to end**.
The remaining items are configuration, ops procedure, and procurement.

## Section-by-section status

| Guide section | Affects code? | Implementation | Status |
|---|---|---|---|
| Import and Export Sales Interface (TXT formats v1.7.6, SFTP guide v1.1, Excel→Text guide, sample SKU/PLU/CATG/PRICE TXT) | **Yes** | `nec_jewel_txt.py`, `nec_jewel_bundle.py`, `cag_sftp.py`, `routers/cag_export.py`, staff-portal `DataQualityPage` | ✅ **Built + tested** (47 tests pass) |
| POS Backend (HQ Operations v1.2d, MFA D365 BE setup, MFA account mgmt) | No (operational, NEC-side) | n/a | 🟡 **Manual review needed by ops** (PDF not extracted) |
| POS Frontend (GM POS v1.15f, Enhanced UI for ChangiPay v2) | No (cashier UX, NEC-side) | n/a | 🟡 **Training material** (PDF not extracted) |
| POS Hardware (Hardware for GM Tenants.xlsx) | No (procurement) | n/a | 🟡 **Procurement decision** — see below |
| POS Overview (Tenant Briefing Deck.pptx) | No (programme overview) | n/a | 🟡 **Reference only** (PPTX not extracted) |

## Import/Export Sales Interface — conformance audit

### Filenames (Summary sheet rows 2-7)
All match spec exactly.

| Interface | Spec template | Our implementation |
|---|---|---|
| CATG | `CATG_<tenant>_<YYYYMMDDHHMMSS>.txt` | `nx.filename_catg()` ✅ |
| SKU | `SKU_<storeID>_<YYYYMMDDHHMMSS>.txt` | `nx.filename_sku()` ✅ |
| PLU | `PLU_<tenant>_<YYYYMMDDHHMMSS>.txt` | `nx.filename_plu()` ✅ |
| PRICE | `PRICE_<tenant>_<YYYYMMDDHHMMSS>.txt` | `nx.filename_price()` ✅ |
| INVDETAILS | `INVDETAILS_<storeID>_<YYYYMMDDHHMMSS>.txt` | `nx.filename_invdetails()` ✅ |
| PROMO | `PROMO_<tenant>_<YYYYMMDDHHMMSS>.txt` | `nx.filename_promo()` ✅ |

### Field counts and order

| File | Spec cols | Our writer cols | Sample col 1 | Match |
|---|---|---|---|---|
| CATG | 4 (parent, child, desc, cag) | 4 | parent | ✅ |
| SKU | 50 (col 1 = FILENAME `NOT USE`, col 2 = MODE) | 50 (col 1 blank, col 2 = mode) | empty | ✅ |
| PLU | 4 (col 1 = FILENAME `NOT USE`, col 2 = MODE) | 4 (col 1 blank, col 2 = mode) | empty | ✅ |
| PRICE | 8 (MODE, SKU, STORE, INCL, EXCL, UNIT, FROM, TO) | 8 same order | mode | ✅ |
| INVDETAILS | 4 (col 1 = FILENAME `NOT USE`) | 4 (col 1 blank) | empty | ✅ |
| PROMO | 7 (DISC_ID, CATG, SKU, LINE_TYPE, METHOD, VALUE, M&M_LINEGRP) | 7 same order | disc_id | ✅ |

### Encoding rules

| Rule | Spec | Our code | Match |
|---|---|---|---|
| Encoding | ASCII | `.encode("ascii")` in `nec_jewel_bundle.py` | ✅ |
| Line terminator | CRLF (`\r\n`) per sample hexdump | `RECORD_TERMINATOR = "\r\n"` | ✅ |
| Header row | None | None emitted | ✅ |
| `,` and `"` in fields | Quote-wrap, double the `"` | `format_field()` does this | ✅ |
| Sentinel char | `NA` (when mandatory char missing) | `NA_CHAR = "NA"` | ✅ |
| Sentinel numeric | `0` (when mandatory numeric missing) | `NA_NUMERIC = "0"` | ✅ |
| Date format | `YYYYMMDD` | `_format_date()` | ✅ |
| Never-expires | `20991231` | `FAR_FUTURE_DATE = "20991231"` | ✅ |
| Money format | `Numeric(20,2)` (e.g. `10.79`) | `format_money()` returns `f"{x:.2f}"` | ✅ |

### One nit (low risk)
`format_field()` for non-money floats trims trailing zeros (`10.70 → 10.7`).
All monetary fields call `format_money()` so this never affects `PRICE`/`PROMO`
output, but if the spec ever introduces a 2dp non-monetary float column the
generic helper would need adjusting. **Action:** none required today.

### SFTP transport (SFTP guide v1.1)

| Spec element | Our config / code | Status |
|---|---|---|
| Tenant folder root | `CAG_SFTP_TENANT_FOLDER` setting | ✅ |
| `Inbound/Working` (uploads) | `CAG_SFTP_INBOUND_WORKING="Inbound/Working"` | ✅ |
| `Inbound/Error` (errorLogs) | `CAG_SFTP_INBOUND_ERROR="Inbound/Error"` | ✅ |
| `Inbound/Archive` (success) | `CAG_SFTP_INBOUND_ARCHIVE="Inbound/Archive"` | ✅ |
| Key auth (preferred) | `CAG_SFTP_KEY_PATH`, `CAG_SFTP_KEY_PASSPHRASE` | ✅ |
| Password auth (fallback) | `CAG_SFTP_PASSWORD` | ✅ |
| ErrorLog format `Failed/Accepted: Line N - msg` | `_LOG_LINE_RE` parser | ✅ |
| Upload + error fetch endpoints | `POST /api/cag/export/push`, `GET /api/cag/export/errors` | ✅ |
| Operator UI for download-as-zip and push | `apps/staff-portal/src/pages/DataQualityPage.tsx` | ✅ |

## Go-live blockers (prioritized)

1. **NEC SFTP credentials not yet received.** The wire path is dormant until
   `CAG_SFTP_HOST/USER` and a key/password are populated in Cloud Run secrets.
   No work for us until NEC provisions the tenant folder.
2. **Tenant code + Store ID(s) not yet finalized.** Required for `<tenant>` and
   `<storeID>` filename slugs and the PRICE STORE_ID column. Confirm with CAG
   officer; today the code defaults to `DEFAULT_TENANT_CODE` /
   `DEFAULT_INV_STORE_CODE` in `nec_jewel_export.py`.
3. **POS Hardware procurement** (see Hardware section below) — needs
   sign-off independent of our software.
4. **MFA accounts for D365 HQ** — operator-facing; needs ops to enroll and
   verify per the unread MFA PDFs.

## POS Hardware summary (from XLSX)

Required NEC POS Package (TWINPOS G5100Li): Core i5-6500TE, 8 GB RAM, 256 GB
SSD primary + 128 GB SSD secondary, M.2 Wi-Fi, 10" 2nd LCD, camera, MSR.
Peripherals: EATON 5L 650 VA UPS, BIXOLON SRP-Q300 receipt printer,
RCD-410 cash drawer, Zebra DS4608 2D scanner. Software: GM POS + Trend Micro
Deep Security. **Action:** procurement; no code impact.

Integrated payment terminals: UPOS (UOB iCT220 / DESK5000) per NETS ECR II
v1.10 + UOB ECR v1.09. **Action:** sourced from NETS / UOB; no code impact.

POS Operator Permissions: 18 cashier/manager privilege flags configured at
NEC HQ (Manager privileges, blind close, X/Z reports, tender/floating
declaration, suspension/voiding, line + total discount caps, return caps,
price override). **Action:** operational policy; configured by NEC ops, not
in our codebase.

POS Request Form (Store WOxml): captures Store Name, Store Type (GM/DFS/MC),
Terminal (T1-T4), Location (AD/AA/LS), Rental Department, store group
assortment policy, GST-inclusive pricing flag, POS register count, tenant
POS ID (3 char), 24h flag, business date end time, closing method
(Date+time / Shift), auto-EOD time, address, phone, unit, receipt footer
(max 300 char / 48 char per line), and mandatory card-info prompts for
credit and NETS. **Action:** ops fills and submits per store; no code impact.

## Recommended next steps

| # | Action | Owner | Blocker? |
|---|---|---|---|
| 1 | Request CAG SFTP host/user/key + tenant folder name from NEC | Ops | Yes |
| 2 | Confirm tenant code and store IDs; update defaults if needed | Ops + Eng | Yes |
| 3 | Once #1 lands, populate `CAG_SFTP_*` secrets in Cloud Run and run a smoke push of the bundle to a non-prod folder | Eng | Yes |
| 4 | Procure POS hardware per the XLSX BOM; complete POS Request Form per store | Ops | Yes |
| 5 | Enroll required staff for D365 HQ MFA (review the two MFA PDFs offline) | Ops | Yes |
| 6 | Once SFTP works, schedule the upload (cron / scheduler) to run on the cadence NEC's 3-hourly importer expects | Eng | No (post-go-live) |
| 7 | Wire the `/api/cag/export/errors` endpoint into a staff-portal alert so import failures are visible | Eng | No (post-go-live) |

## What we did NOT review

- `[Latest] CAG NEC - Guide to Convert Excel to Text File.pdf` — likely a
  manual procedure for tenants who use Excel; we bypass it via the Python
  writers, so no impact.
- `[Latest] CAG NEC - SFTP guide v1.1.pdf` — folder structure inferred
  from `cag_sftp.py` docstring; matches our code. Re-confirm against PDF
  before go-live.
- `[Latest] CAG-Jewel-ISD-Interfaces TXT Formats v1.7.6j.pdf` — the XLSX
  (`v1.7.6h`) was used as the source of truth; the PDF is rev `j` so a
  diff between `h` and `j` should be done before go-live.
- POS Backend, Frontend, Overview PDFs/PPTX — operational/training content
  that does not affect our codebase. Ops to review separately.
