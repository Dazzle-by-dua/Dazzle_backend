from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from app.config import CORS_ORIGINS, UPLOAD_DIR
from app.database import init_db
from app.routers import (
    auth,
    products,
    categories,
    orders,
    customers,
    reviews,
    offers,
    homepage,
    settings,
    navigation,
    pages,
    media,
    dashboard,
    backup
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: ensure tables & initial data exist
    init_db(seed_if_empty=True)
    yield
    # Shutdown logic if any

app = FastAPI(
    title="Dazzle by Dua - Fine Jewellery REST API",
    description="""
    Production-ready REST API backend for Dazzle by Dua luxury jewellery e-commerce platform.
    Features:
    - Products CRUD, stock toggle, variants & photography
    - Category management & auto product counters
    - Orders lifecycle, status pipeline & fulfillment tracking
    - Customer analytics & order history
    - 5-Star Reviews submission, approval & moderation
    - Offers, Coupons validation & bundle combos
    - Homepage 9 configurable sections manager
    - Store settings, currency, free shipping threshold
    - Navigation menu hierarchies
    - Static policy pages & care guides
    - Media uploads & asset library
    - Secure Admin JWT authentication & protected routes
    - Live dashboard stats & inventory monitoring
    - Full store JSON database backup/export & restore
    """,
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan
)

# CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS if CORS_ORIGINS != ["*"] else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve uploaded static images
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")

# Include all modular routers
app.include_router(auth.router)
app.include_router(products.router)
app.include_router(categories.router)
app.include_router(orders.router)
app.include_router(customers.router)
app.include_router(reviews.router)
app.include_router(offers.router)
app.include_router(homepage.router)
app.include_router(settings.router)
app.include_router(navigation.router)
app.include_router(pages.router)
app.include_router(media.router)
app.include_router(dashboard.router)
app.include_router(backup.router)

@app.get("/", tags=["Root"])
def root():
    return {
        "brand": "Dazzle by Dua",
        "tagline": "Fine Jewellery",
        "api_status": "Online & Operational",
        "version": "1.0.0",
        "documentation": "/docs",
        "redoc": "/redoc"
    }

@app.get("/api/health", tags=["Health"])
def health_check():
    return {"status": "ok", "service": "dazzle-backend"}
