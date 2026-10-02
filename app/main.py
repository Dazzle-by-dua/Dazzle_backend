from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from app.config import CORS_ORIGINS, UPLOAD_DIR
from app.database import init_db, close_db, check_db_health
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
    upload,
    dashboard,
    backup
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Lifecycle: Initialize MongoDB connection pool & seeds
    await init_db()
    # Lifecycle: Verify Cloudinary & Razorpay configuration & connection
    import asyncio
    from app.cloudinary_service import verify_cloudinary_connection
    from app.razorpay_service import verify_razorpay_configuration
    await asyncio.to_thread(verify_cloudinary_connection)
    await asyncio.to_thread(verify_razorpay_configuration)
    yield
    # Cleanup: Close MongoDB client connection pool cleanly
    await close_db()

app = FastAPI(
    title="Dazzle by Dua - Fine Jewellery REST API",
    description="""
    Production-ready REST API backend for Dazzle by Dua luxury jewellery e-commerce platform.
    MongoDB Integrated:
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
    version="1.1.0",
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
app.include_router(upload.router)
app.include_router(dashboard.router)
app.include_router(backup.router)

@app.get("/", tags=["Root"])
def root():
    return {
        "brand": "Dazzle by Dua",
        "tagline": "Fine Jewellery",
        "api_status": "Online & Operational",
        "database": "MongoDB (Motor)",
        "version": "1.1.0",
        "documentation": "/docs",
        "redoc": "/redoc"
    }

@app.get("/health", tags=["Health"])
async def health():
    """Production health-check endpoint reporting server & MongoDB connection status"""
    db_health = await check_db_health()
    db_status = "connected" if db_health.get("connected", False) else "disconnected"
    return {
        "status": "ok",
        "database": db_status
    }

@app.get("/api/health", tags=["Health"])
async def health_check():
    """Extended health check with detailed database metrics, Cloudinary & Razorpay status"""
    from app.cloudinary_service import get_cloudinary_health
    from app.razorpay_service import get_razorpay_status
    db_health = await check_db_health()
    cloud_health = get_cloudinary_health()
    rzp_health = get_razorpay_status()
    return {
        "status": "ok",
        "service": "dazzle-backend",
        "database": db_health,
        "cloudinary": cloud_health,
        "razorpay": rzp_health
    }

@app.get("/api/health/cloudinary", tags=["Health"])
async def cloudinary_health():
    """Dedicated Cloudinary connection & configuration health check"""
    from app.cloudinary_service import get_cloudinary_health
    return get_cloudinary_health()

@app.get("/api/health/razorpay", tags=["Health"])
async def razorpay_health():
    """Dedicated Razorpay connection & configuration health check"""
    from app.razorpay_service import get_razorpay_status
    return get_razorpay_status()
