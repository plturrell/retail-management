from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import (
    barcode,
    brands,
    cag_xml,
    categories,
    health,
    inventory,
    nec_import,
    orders,
    plus,
    prices,
    promotions,
    sales,
    skus,
    stores,
    users,
    pricing_engine,
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
app.include_router(pricing_engine.router)
