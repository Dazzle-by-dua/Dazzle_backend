from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from app.config import CORS_ORIGINS, UPLOAD_DIR, IS_PRODUCTION
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
    backup,
    webhooks,
    customer_auth
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
    version="1.2.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan
)

# Security Headers Middleware
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if IS_PRODUCTION:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response

PUBLIC_STOREFRONT_PATHS = {
    "/api/auth/login",
    "/api/auth/login/2fa",
    "/api/customer/auth/signup/initiate",
    "/api/customer/auth/signup/verify-otp",
    "/api/customer/auth/signup/resend-otp",
    "/api/customer/auth/signup/complete",
    "/api/customer/auth/login",
    "/api/customer/auth/forgot-password",
    "/api/customer/auth/verify-reset-otp",
    "/api/customer/auth/reset-password",
    "/api/delivery-charge",
    "/api/offers/coupons/validate",
    "/api/reviews",
}

def is_cookie_authenticated_request(request: Request) -> bool:
    """
    Determine if the incoming mutation request is authenticating via ambient browser cookies
    and thus subject to CSRF Origin/Referer verification.
    """
    path = request.url.path.rstrip("/").lower() or "/"
    if (
        path in PUBLIC_STOREFRONT_PATHS
        or path.startswith("/api/orders/razorpay")
        or path.startswith("/api/webhooks")
    ):
        return False

    auth_header = request.headers.get("authorization")
    if auth_header and auth_header.lower().startswith("bearer "):
        return False

    admin_cookie = request.cookies.get("admin_token")
    customer_cookie = request.cookies.get("customer_token")

    # Storefront orders: cookie-authenticated only if placed with a customer session cookie
    if path == "/api/orders":
        return bool(customer_cookie)

    # Customer protected endpoints
    if path.startswith("/api/customer"):
        return bool(customer_cookie)

    # Admin mutation endpoints
    return bool(admin_cookie)

# CSRF & Origin Verification Middleware for Cookie-Authenticated Requests
@app.middleware("http")
async def verify_csrf_and_origin(request: Request, call_next):
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        if is_cookie_authenticated_request(request):
            origin = request.headers.get("origin")
            referer = request.headers.get("referer")

            # 1. Reject when both Origin and Referer headers are missing
            if not origin and not referer:
                return JSONResponse(
                    status_code=403,
                    content={"detail": "Cross-Origin Request Blocked: Missing Origin and Referer headers."}
                )

            # 2. Reject Origin: null explicitly (sandboxed iframes, local file attacks) and unauthorized origins
            if origin:
                if origin.strip().lower() == "null" or origin not in CORS_ORIGINS:
                    return JSONResponse(
                        status_code=403,
                        content={"detail": "Cross-Origin Request Blocked: Unauthorized Origin."}
                    )

            # 3. Reject unauthorized or malformed referers
            if referer:
                try:
                    from urllib.parse import urlparse
                    ref_parts = urlparse(referer)
                    if not ref_parts.scheme or not ref_parts.netloc:
                        return JSONResponse(
                            status_code=403,
                            content={"detail": "Cross-Origin Request Blocked: Malformed Referer."}
                        )
                    ref_origin = f"{ref_parts.scheme}://{ref_parts.netloc}"
                    if ref_origin not in CORS_ORIGINS:
                        return JSONResponse(
                            status_code=403,
                            content={"detail": "Cross-Origin Request Blocked: Unauthorized Referer."}
                        )
                except Exception:
                    return JSONResponse(
                        status_code=403,
                        content={"detail": "Cross-Origin Request Blocked: Malformed Referer."}
                    )

    return await call_next(request)

# CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve uploaded static images
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")

# Include all modular routers
app.include_router(auth.router)
app.include_router(customer_auth.router)
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
app.include_router(webhooks.router)


@app.get("/", tags=["Root"])
def root():
    return {
        "brand": "Dazzle by Dua",
        "tagline": "Fine Jewellery",
        "api_status": "Online & Operational",
        "database": "MongoDB (Motor)",
        "version": "1.2.0",
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
