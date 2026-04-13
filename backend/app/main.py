import logging
import logging.config

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings

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
    banking,
    barcode,
    brands,
    cag_xml,
    categories,
    health,
    hr,
    inventory,
    nec_import,
    orders,
    plus,
    prices,
    promotions,
    sales,
    schedules,
    skus,
    stores,
    timesheets,
    users,
    pricing_engine,
    payroll,
)

app = FastAPI(
    title="RetailSG API",
    description="Backend API for RetailSG retail management system",
    version="0.1.0",
)

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
app.include_router(skus.router)
app.include_router(categories.router)
app.include_router(brands.router)
app.include_router(inventory.router)
app.include_router(orders.router)
app.include_router(prices.router)
app.include_router(promotions.router)
app.include_router(plus.router)
app.include_router(barcode.router)
app.include_router(cag_xml.router)
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
