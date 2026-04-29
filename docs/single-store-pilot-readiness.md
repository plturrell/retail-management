# RetailSG Single-Store Pilot Readiness

## Cross-Repo Environment Checklist

### RetailSG Backend
- Set Firebase Admin credentials so Firestore-backed auth and writes work in the target environment.
- Confirm Firestore contains UUID-backed `users`, `stores`, `inventory`, `stock`, `prices`, `recommendations`, and supply-chain subcollections.
- Set `OPENCLAW_WEBHOOK_URL` if you want ambient digests or approval nudges to be pushed out after analysis runs.
- Set the production `CORS_ORIGINS` values to the actual web and iOS-accessible API origins for the pilot.

### Multica / Snowflake
- Set the Multica inventory-analysis endpoint so RetailSG can request advisory analysis without blocking manual operations.
- Keep Multica configured with wildcard-capable origin parsing through `CORS_ALLOWED_ORIGINS` or explicit allowed origins.
- Keep `FRONTEND_ORIGIN` concrete for flows that need an app URL instead of a wildcard.
- Configure Snowflake credentials and warehouse access for read-heavy inventory and pricing analysis only.
- Confirm Multica output maps to the RetailSG recommendation contract instead of a custom client-specific format.

### OpenClaw
- Point the RetailSG plugin at the live RetailSG API base URL and default pilot `store_id`.
- Confirm the plugin has access to the ambient manager tools:
  - `retailsg_manager_summary`
  - `retailsg_supply_chain_summary`
  - `retailsg_manager_alerts`
  - `retailsg_recommendation_list`
  - `retailsg_recommendation_approve`
  - `retailsg_recommendation_reject`
  - `retailsg_recommendation_apply`
- Keep OpenClaw focused on alerts, summaries, and approval prompts rather than supply-chain CRUD.

### Clients
- Confirm the web staff portal is pointed at the same RetailSG API and Firebase project as iOS.
- Confirm the pilot manager account has a `manager` or `owner` store role in RetailSG.
- Verify the selected store in web and iOS matches the OpenClaw default store for the pilot.

## Single-Store Integration Checklist

### Manager Workflow
- Manager can create and update suppliers from web and iOS.
- Manager can create purchase orders, receive them, and see purchased-stage quantities update.
- Manager can create BOM recipes, create work orders, start them, complete them, and see material-to-finished conversion update.
- Manager can create stock transfers, receive them, and see stage-ledger plus finished-stock updates.
- Staff users are blocked from manager copilot and supply-chain routes.

### Copilot Workflow
- Triggering analysis persists recommendations in RetailSG even when Multica is unavailable.
- Re-running analysis within the same dedupe window reuses existing recommendations unless `force_refresh=true`.
- Manager can approve, reject, and apply recommendations from web and iOS.
- Applying a reorder recommendation creates the downstream purchase order, work order, or transfer in RetailSG.
- Applying a price recommendation writes a new price record without auto-applying unrelated inventory actions.

### Ambient Assistant Workflow
- OpenClaw can fetch manager summary and supply-chain summary for the pilot store.
- OpenClaw can list pending recommendations without expecting legacy SKU fields like `name` or `base_price`.
- OpenClaw can approve, reject, and apply recommendations against the live RetailSG endpoints.
- Optional alert or digest delivery uses persisted RetailSG recommendation data, not transient local state.

### Operational Sign-Off
- Firestore remains the write path for manager actions.
- Snowflake and Multica remain advisory; manual operations still work if analysis is offline.
- Web, iOS, and OpenClaw all display the same recommendation state for the same `store_id`.
- The pilot store has one agreed source of truth for purchased, material, and finished stage inventory.
