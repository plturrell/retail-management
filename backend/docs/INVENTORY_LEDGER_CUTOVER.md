# Inventory ledger cutover plan

This document tracks the migration of inventory ledger reads from Firestore
(`stores/{store_id}/inventory_adjustments`) to TiDB Cloud
(`stock_movements`). Writes already dual-write today.

Owner: backend lead. Update the **Status** column as phases land.

| # | Phase | Status |
|---|---|---|
| 1 | Dual-write (Firestore primary, TiDB additive) | ✅ in prod |
| 2 | Backfill historical Firestore movements into TiDB | ⬜ not started |
| 3 | Parity check (continuous diff dashboard) | ⬜ not started |
| 4 | Read-cutover for low-risk endpoints | ⬜ not started |
| 5 | Read-cutover for manager copilot / analytics | ⬜ not started |
| 6 | Stop Firestore writes; archive collection | ⬜ not started |

---

## Phase 1 — Dual-write *(done)*

What's live:

- `app/services/inventory_ledger.py::record_movement` writes a
  `stock_movements` row alongside every Firestore adjustment.
- Wired in `app/routers/inventory.py::adjust_inventory` and the new
  `/inventory/import-csv` endpoint.
- Failures in the SQL leg are logged at WARN and **never** raise. Callers
  rely on this — do not change it without updating both call sites and
  this document.
- `/api/health/tidb` reports `disabled` / `ok` / `error` so liveness is
  observable.

Open items inside Phase 1:

- Wire dual-write into `app/services/supply_chain.py::adjust_stage_inventory`
  (purchase-order receipts, work orders, transfers). Today only the
  manager-driven adjustment path writes the ledger.

## Phase 2 — Backfill

Goal: every existing Firestore adjustment from before TiDB was attached
appears in `stock_movements` with the same `(store_id, sku_id, event_time)`
ordering.

Approach:

1. Add a one-shot script `tools/scripts/backfill_inventory_ledger.py`:
   - Iterates `stores/*/inventory_adjustments` ordered by `created_at`.
   - For each Firestore doc, calls `record_movement` with
     `event_time=created_at`, `reference_type="firestore_backfill"`,
     `reference_id=<firestore_doc_id>`.
   - Idempotent: skips a row if a `stock_movements` row already exists
     with `reference_type="firestore_backfill"` AND `reference_id` matching.
2. Run against staging; verify counts match per `(store_id, sku_id)`.
3. Run against prod during a quiet window. Backfill ≈ append-only inserts;
   safe to run with traffic.

Acceptance:

- For every `(store_id, sku_id)` in Firestore, count and sum of
  `quantity_delta` matches `delta_qty` in TiDB ± live in-flight writes.

## Phase 3 — Parity check

Goal: detect divergence between the two stores in *near* real time before
flipping reads.

Approach:

1. Cron `tools/scripts/inventory_ledger_parity.py` every 15 min:
   - For the last 30 min of writes, compare:
     - row count per `(store_id, sku_id)` in Firestore vs TiDB
     - sum of `quantity_delta` per `(store_id, sku_id)`
   - Emit one structured log line per discrepancy. Aggregate into
     Cloud Monitoring / Datadog.
2. Threshold: 0 discrepancies tolerated for 7 consecutive days before
   moving to Phase 4.

Acceptance:

- Dashboard shows green for 7 days running.
- Manual probes (force a Firestore write while TiDB is intentionally
  unreachable, then restore) confirm the parity check raises.

## Phase 4 — Read-cutover for low-risk endpoints

Candidates (low blast radius, easy to roll back):

- `routers/inventory.py::list_recent_adjustments` (if/when added) — reads
  per-SKU history. Today the iOS client renders this from the manager
  copilot summary, not directly from Firestore.
- A new analytics-only endpoint (`/copilot/movements`) that reads from
  TiDB exclusively. Add this alongside the existing endpoints; do not
  remove any current path.

Roll-back: feature flag `INVENTORY_LEDGER_READ_FROM_TIDB` gating the new
service-layer call. Default off; flip per environment.

## Phase 5 — Manager copilot + analytics cutover

Higher-risk because the manager copilot's recommendation engine reads
adjustments to compute days-of-cover, anomaly detection, etc.

Approach:

1. In `app/services/manager_copilot.py`, replace direct Firestore reads
   with the same `inventory_ledger.list_movements_for_sku` plus a couple
   of helper queries (running totals, last-N).
2. Behind the same feature flag.
3. Run side-by-side for a week — produce both Firestore-derived and
   TiDB-derived recommendations, log when they diverge.
4. Flip the flag once divergence < 0.5%.

## Phase 6 — Stop Firestore writes

Once Phases 4 & 5 are stable:

1. Delete the Firestore write path in
   `app/services/inventory_ledger.py::record_movement` consumers — the
   function itself stays as a TiDB-only writer.
2. Add a one-shot archive script that snapshots
   `stores/*/inventory_adjustments` to GCS and then deletes the Firestore
   docs. Keep the snapshot for a year.
3. Drop unused Firestore indexes.

## Roll-back at any phase

- Phases 1–3: nothing to do; Firestore is still authoritative.
- Phase 4: flip `INVENTORY_LEDGER_READ_FROM_TIDB=false`.
- Phase 5: same flag covers manager-copilot reads.
- Phase 6: restore from the GCS snapshot. (Costly. Don't reach this state
  unless Phase 5 has been steady for ≥ 30 days.)

## Operational guardrails

- Always treat the SQL leg as **best-effort** in dual-write paths. The
  `try/except` in `record_movement` is load-bearing.
- Never run alembic migrations during a deploy that also changes the SQL
  read path. Migrate, verify health, *then* deploy code that reads.
- TiDB connection pool: pre-ping on, recycle 30 min. Bump
  `pool_recycle` if you start seeing "MySQL server has gone away".
- Keep `TIDB_DATABASE_URL` empty in unrelated environments (e.g.
  one-off test instances). The layer self-disables and stays out of
  the way.
