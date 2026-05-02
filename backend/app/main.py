import logging
import logging.config

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.config import settings
from app.rate_limit import limiter

if settings.ENVIRONMENT == "production":
    logging.config.dictConfig({
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "json": {
                "()": "pythonjsonlogger.jsonlogger.JsonFormatter",
                "format": "%(asctime)s %(name)s %(levelname)s %(message)s",
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "json",
                "stream": "ext://sys.stdout",
            },
        },
        "root": {"level": "INFO", "handlers": ["console"]},
    })
else:
    logging.basicConfig(level=logging.INFO)
from app.routers import (
    ai_jobs,
    analytics,
    audit as audit_router,
    auth_lockout,
    banking,
    webauthn as webauthn_router,
    barcode,
    brands,
    cag_config as cag_config_router,
    cag_export,
    cag_xml,
    categories,
    finance,
    health,
    hr,
    inventory,
    manager_copilot,
    master_data,
    nec_import,
    orders,
    plus,
    prices,
    promotions,
    reports,
    sales,
    schedules,
    supply_chain,
    skus,
    stores,
    timesheets,
    users,
    pricing_engine,
    payroll,
    pos_labelling,
    stock_checks,
    data_quality,
    supplier_review,
)
# Dormant (SQLAlchemy) routers - not yet migrated to Firestore; intentionally not imported:
# customers, intelligence, marketing, purchases, staff_hr, suppliers

# Auto-generated docs are served at /docs (Swagger UI) and /redoc (ReDoc).
# `openapi_tags` groups routes in the rendered docs so a casual reader can
# scan by domain (Master Data, Orders, Payroll …) instead of by file name.
# Most endpoints require a Firebase Authentication ID token in the
# `Authorization: Bearer <token>` header — that's documented globally via the
# `components.securitySchemes` block we patch below.
OPENAPI_TAGS = [
    {"name": "Master Data", "description": "Catalog, SKU/PLU minting, NEC publishing."},
    {"name": "Inventory", "description": "Stock levels, ledger, stock-checks."},
    {"name": "Orders & Sales", "description": "POS sales ingest, order lifecycle."},
    {"name": "Pricing", "description": "Price ladders, promotions, pricing engine."},
    {"name": "Manager Copilot", "description": "AI recommendations and ops insights."},
    {"name": "HR & Payroll", "description": "Schedules, timesheets, payroll runs, CPF/IRAS."},
    {"name": "Finance", "description": "Banking reconciliation, reports."},
    {"name": "CAG / NEC", "description": "Jewel POS file exchange and config."},
    {"name": "Auth", "description": "Lockout, WebAuthn, audit log."},
    {"name": "Admin", "description": "Stores, users, audit, data quality."},
    {"name": "AI Jobs", "description": "Batch AI dispatch, document OCR jobs."},
    {"name": "Health", "description": "Liveness/readiness probes."},
]

app = FastAPI(
    title="RetailSG API",
    description=(
        "Backend API for the VictoriaEnso retail management system.\n\n"
        "**Authentication.** Most endpoints require a Firebase ID token in the "
        "`Authorization: Bearer <token>` header. The token is verified per "
        "request and decoded into a user document with role + store assignments. "
        "Endpoints document any role gates (staff / manager / owner / system_admin) "
        "in their docstrings; on a role mismatch the server returns **403** "
        "with `detail` describing the requirement. Missing or expired tokens "
        "return **401**.\n\n"
        "**Rate limiting.** Auth-adjacent routes (login attempts, password "
        "resets) are rate-limited via SlowAPI; exceeding the bucket returns "
        "**429** with a `Retry-After` header.\n\n"
        "**Error shape.** All errors follow FastAPI's default `{ \"detail\": ... }` "
        "envelope. 4xx responses carry a string or object describing the failure; "
        "5xx responses are logged with a request id."
    ),
    version="0.1.0",
    contact={
        "name": "VictoriaEnso engineering",
        "email": "engineering@victoriaenso.sg",
    },
    openapi_tags=OPENAPI_TAGS,
)


# Patch the OpenAPI spec to declare the Bearer security scheme globally.
# We can't pass `security` as a top-level FastAPI ctor arg, so we override
# the `openapi()` builder once and cache the result. Swagger UI uses this to
# render padlock icons + an "Authorize" button on every protected route.
def _custom_openapi():  # pragma: no cover — schema generation, not runtime path
    if app.openapi_schema:
        return app.openapi_schema
    from fastapi.openapi.utils import get_openapi
    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
        tags=OPENAPI_TAGS,
        contact=app.contact,
    )
    components = schema.setdefault("components", {})
    components.setdefault("securitySchemes", {})["FirebaseBearer"] = {
        "type": "http",
        "scheme": "bearer",
        "bearerFormat": "Firebase ID token",
        "description": (
            "Firebase Authentication ID token, obtained from "
            "`firebase.auth().currentUser.getIdToken()` on the client."
        ),
    }
    # Apply globally; individual public routes (health, login-failure ping)
    # can opt out by setting `security=[]` in their decorator.
    schema["security"] = [{"FirebaseBearer": []}]
    app.openapi_schema = schema
    return schema


app.openapi = _custom_openapi  # type: ignore[assignment]

# Rate limiting (used by auth/password endpoints — see app.rate_limit)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(health.router)
app.include_router(stores.router)
app.include_router(users.router)
app.include_router(audit_router.router)
app.include_router(auth_lockout.router)
app.include_router(webauthn_router.router)
app.include_router(skus.router)
app.include_router(categories.router)
app.include_router(brands.router)
app.include_router(inventory.router)
app.include_router(manager_copilot.router)
app.include_router(master_data.router)
app.include_router(supply_chain.router)
app.include_router(orders.router)
app.include_router(prices.router)
app.include_router(promotions.router)
app.include_router(plus.router)
app.include_router(barcode.router)
app.include_router(cag_xml.router)
app.include_router(cag_export.router)
app.include_router(cag_config_router.router)
app.include_router(nec_import.router)
app.include_router(sales.router)
app.include_router(schedules.router)
app.include_router(timesheets.router)
app.include_router(pricing_engine.router)
app.include_router(hr.router)
app.include_router(payroll.router)
app.include_router(analytics.router)
app.include_router(ai_jobs.router)
app.include_router(banking.router)
app.include_router(finance.router)
app.include_router(reports.router)
app.include_router(stock_checks.router)
app.include_router(data_quality.router)
app.include_router(supplier_review.router)
app.include_router(pos_labelling.router)
