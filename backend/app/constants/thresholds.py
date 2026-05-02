"""Inventory + external-service tunable thresholds.

These are *defaults*. A future store-settings document (see backlog ticket
"Add Store-Level Configuration for Thresholds") will let owners override on
a per-store basis. Until that lands, code reads these constants directly.
"""

#: Default cutoff used by the Multica AI inventory health analyser when a
#: caller doesn't pass an explicit value. Below this on-hand quantity, a SKU
#: is considered "low stock" and may surface as a critical_skus suggestion.
DEFAULT_LOW_STOCK_THRESHOLD: int = 5

#: HTTP timeout for the Multica AI Platform inventory analysis call. The
#: vendor SLA is "<30s warm, 45s cold start", so we wait the full cold path
#: before declaring the service down and returning the offline fallback.
MULTICA_TIMEOUT_SECONDS: float = 45.0

#: Tenacity retry attempts for transient Multica failures (timeout, 5xx).
#: Three is enough to ride through a single cold-start retry + a network
#: blip without DOSing the vendor.
MULTICA_MAX_RETRIES: int = 3

#: Lower bound of the exponential backoff between Multica retries.
MULTICA_RETRY_MIN_SECONDS: float = 1.0

#: Upper bound of the exponential backoff. Keeps total worst-case retry
#: budget under ~25s so the FastAPI request doesn't outlive the load
#: balancer's idle timeout (60s).
MULTICA_RETRY_MAX_SECONDS: float = 10.0

#: Multiplier used when computing whether finished-stock on-hand is "well
#: above" reorder level — triggers the markdown-review recommendation in
#: manager_copilot.
SURPLUS_REORDER_MULTIPLIER: int = 4

#: Multiplier on reorder_qty for the same surplus check (covers cases where
#: reorder_level is zero but reorder_qty is set).
SURPLUS_REORDER_QTY_MULTIPLIER: int = 3

#: Hard floor for the surplus check — units on hand greater than this count
#: as surplus even if both reorder figures are zero.
SURPLUS_MIN_FLOOR: int = 12

#: Margin floor below which we don't suggest a *premium* price bump on a
#: low-stock fast mover. Below ~20% gross margin, a price hike doesn't
#: meaningfully protect margin and the recommendation is noisy.
PREMIUM_PRICE_MIN_MARGIN_RATIO: float = 0.20

#: Markdown applied to current_price when proposing a slow-mover discount.
#: Conservative single-digit percent — the recommendation is *for review*,
#: not auto-applied.
SLOW_MOVER_MARKDOWN_FACTOR: float = 0.95

#: Bump applied to current_price when proposing a fast-mover premium.
PREMIUM_PRICE_FACTOR: float = 1.04
