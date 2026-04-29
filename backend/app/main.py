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

app = FastAPI(
    title="RetailSG API",
    description="Backend API for RetailSG retail management system",
    version="0.1.0",
)

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
